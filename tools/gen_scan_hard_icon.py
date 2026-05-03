"""

Regenerate exe/actions/scan_hard.png (Ping / hard scan toolbar).



If assets/reference_scan_hard_dish.png exists, it is normalized (transparent +

toolbar grey) via normalize_scan_hard_png.py. Otherwise falls back to Lucide

satellite-dish vectors.



Then: python tools/sync_assets_pngs.py

"""

from __future__ import annotations



from pathlib import Path



ROOT = Path(__file__).resolve().parent.parent

OUT = ROOT / "exe" / "actions" / "scan_hard.png"

REF = ROOT / "assets" / "reference_scan_hard_dish.png"





def main() -> None:

    if REF.is_file():

        from normalize_scan_hard_png import normalize



        normalize(REF, OUT)

    else:

        from lucide_satellite_dish_png import DEFAULT_FG, render_lucide_satellite_dish_png



        render_lucide_satellite_dish_png(OUT, 127, 127, fg=DEFAULT_FG)

        print(f"Wrote {OUT} (Lucide satellite-dish fallback)")





if __name__ == "__main__":

    main()


