from playwright.sync_api import sync_playwright
import os
BASE=os.path.dirname(os.path.abspath(__file__))
out="/sessions/fervent-dazzling-cray/mnt/PromoLens/PromoLens_AI_Blog.pdf"
with sync_playwright() as p:
    b=p.chromium.launch(args=["--no-sandbox","--disable-dev-shm-usage","--disable-gpu"])
    pg=b.new_page()
    pg.goto("file://"+os.path.join(BASE,"blog.html"))
    pg.wait_for_timeout(800)
    pg.pdf(path=out, format="A4", print_background=True,
           margin={"top":"0","bottom":"0","left":"0","right":"0"})
    b.close()
print("PDF_OK", os.path.getsize(out))
