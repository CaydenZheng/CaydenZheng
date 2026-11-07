"""Export the approved HTML composition into linked, GitHub-safe SVG panels.

Requires Python, Playwright with Chromium, and PyMuPDF. Run from any directory.
The SVGs contain vector outlines, so they do not depend on installed reader fonts.
"""

from pathlib import Path
import json
import re

import fitz
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets" / "profile"
ASSETS.mkdir(exist_ok=True)


def save_crop(document, rect, name, pixel_width):
    pdf_page = document[0]
    pdf_page.set_cropbox(pdf_page.mediabox)
    crop = fitz.Rect(*(value * 0.75 for value in rect)) & pdf_page.mediabox
    pdf_page.set_cropbox(crop)
    svg = pdf_page.get_svg_image(text_as_path=True)
    svg = re.sub(r'width="[^"]+"', f'width="{pixel_width:g}"', svg, count=1)
    # Mobile cards use a wide intrinsic size so GitHub's max-width rule makes
    # each one fill the available row; desktop cards retain their half widths.
    height = (rect[3] - rect[1]) * pixel_width / (rect[2] - rect[0])
    svg = re.sub(r'height="[^"]+"', f'height="{height:g}"', svg, count=1)
    svg = svg.replace('</defs>', '</defs><rect width="100%" height="100%" fill="#ffffff"/>', 1)
    (ASSETS / name).write_text(svg, encoding="utf-8")


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    for mobile in (False, True):
        width = 324 if mobile else 846
        page = browser.new_page(viewport={"width": 390 if mobile else 1440, "height": 1100})
        page.goto((ROOT / "design" / "profile.html").as_uri(), wait_until="load")
        # Freeze the rules active at the review viewport. Otherwise printing an
        # 846px-wide artboard can unexpectedly activate tablet media queries.
        css = page.evaluate("""() => {
          const flatten = rules => [...rules].flatMap(rule => {
            if (rule instanceof CSSMediaRule) {
              return matchMedia(rule.conditionText).matches ? flatten(rule.cssRules) : [];
            }
            return [rule.cssText];
          });
          return [...document.styleSheets].flatMap(sheet => flatten(sheet.cssRules)).join('\\n');
        }""")
        composition = page.locator(".composition").evaluate("element => element.outerHTML")
        # Keep the approved layout in screen media while printing vector artwork.
        page.set_content(f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
          <style>{css}
          html,body{{margin:0!important;padding:0!important;width:{width}px;background:white}}
          .composition{{width:{width}px;margin:0!important}}
          .closing,.text-version{{display:none}}
          .text-highlight{{background:#f8e9a3}}
          *{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
          </style></head><body>{composition}</body></html>""")
        page.emulate_media(media="screen")
        page.evaluate("document.fonts.ready")
        bounds = page.evaluate("""() => {
          const rect = selector => {const r=document.querySelector(selector).getBoundingClientRect();return [r.x,r.y,r.right,r.bottom]};
          return {intro:rect('.intro'),heading:rect('.works-heading'),rag:rect('.featured'),
            secondary:rect('.secondary'),mindtrace:rect('.project'),sasrec:rect('.project+.project')};
        }""")
        height = bounds["secondary"][3]
        pdf = page.pdf(width=f"{width}px", height=f"{height}px", print_background=True,
                       margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
        document = fitz.open(stream=pdf, filetype="pdf")
        assert len(document) == 1, "Expected one artboard"
        suffix = "-mobile" if mobile else ""
        save_crop(document, [0, 0, width, bounds["heading"][3]], f"about{suffix}.svg", width)
        save_crop(document, bounds["rag"], f"rag{suffix}.svg", width)
        if mobile:
            # Each card gets its own link and a full-width image on narrow screens.
            save_crop(document, bounds["mindtrace"], "mindtrace-mobile.svg", 846)
            sasrec_rect = list(bounds["sasrec"])
            sasrec_rect[3] = height  # Include the composition's final horizontal rule.
            save_crop(document, sasrec_rect, "sasrec-mobile.svg", 846)
        else:
            mid = bounds["sasrec"][0]
            top = bounds["secondary"][1]
            save_crop(document, [0, top, mid, height], "mindtrace.svg", mid)
            save_crop(document, [mid, top, width, height], "sasrec.svg", width-mid)
        print(json.dumps({"mobile": mobile, "width": width, "height": height}))
        document.close()
        page.close()
    browser.close()
