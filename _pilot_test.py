# -*- coding: utf-8 -*-
import asyncio, sys, time
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path
from tts_tui import TTSStudio, PRODUCT

before = {f.name for f in PRODUCT.glob("*.mp3")}

async def test():
    app = TTSStudio()
    async with app.run_test(size=(150, 48)) as pilot:
        # 1. Chuyển view
        for v in ["products", "words", "video", "settings", "home"]:
            app.switch_view(v)
            await pilot.pause()
            assert app.query_one(f"#view-{v}").has_class("active"), f"view {v} fail"
        print("1. Chuyển 5 view: OK")

        # 2. Kho từ load
        app.switch_view("words"); await pilot.pause()
        print("2. Kho từ rows:", app.query_one("#word-table").row_count)
        assert app.query_one("#word-table").row_count > 300

        # 3. Quét từ
        app.switch_view("home"); await pilot.pause()
        ta = app.query_one("#text-input")
        ta.text = "Lâm Dư nói: wifi hết mạng rồi, monster xuất hiện!"
        app.do_scan(); await pilot.pause(0.3)
        print("3. Scan rows:", app.query_one("#scan-table").row_count)
        assert app.query_one("#scan-table").row_count >= 1

        # 4. Render TTS (worker)
        ta.text = "Lâm Dư cười, bỏ đi. Ưu đãi 15 phần trăm."
        t0 = time.time()
        app.do_generate()
        new_file = None
        for _ in range(120):
            await pilot.pause(0.5)
            new = {f.name for f in PRODUCT.glob("*.mp3")} - before
            if new:
                new_file = new.pop()
                break
        assert new_file, "Render không ra file"
        print(f"4. Render OK: {new_file} ({time.time()-t0:.0f}s)")
        await pilot.pause(1)

        # 5. Bảng sản phẩm có file mới
        print("5. Sản phẩm rows:", app.query_one("#prod-table").row_count)
        assert app.query_one("#prod-table").row_count >= 3

        # 6. State tự lưu
        assert app.state["text"] == "Lâm Dư cười, bỏ đi. Ưu đãi 15 phần trăm."
        print("6. Auto-save state: OK")

asyncio.run(test())
print("ALL TESTS PASSED")
