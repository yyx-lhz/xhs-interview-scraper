from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "notes.sqlite"
PLAYWRIGHT_USER_DIR = DATA_DIR / "playwright-profile"
PLAYWRIGHT_USER_DIR.mkdir(exist_ok=True)

# Major Chinese internet companies — list of (display_name, search_keyword)
COMPANIES: list[tuple[str, str]] = [
    ("字节跳动", "字节跳动面经"),
    ("腾讯", "腾讯面经"),
    ("阿里巴巴", "阿里巴巴面经"),
    ("百度", "百度面经"),
    ("美团", "美团面经"),
    ("京东", "京东面经"),
    ("拼多多", "拼多多面经"),
    ("滴滴", "滴滴面经"),
    ("网易", "网易面经"),
    ("小米", "小米面经"),
    ("华为", "华为面经"),
    ("快手", "快手面经"),
    ("小红书", "小红书面经"),
    ("bilibili", "B站面经"),
    ("携程", "携程面经"),
    ("微博", "微博面经"),
    ("蚂蚁集团", "蚂蚁面经"),
    ("知乎", "知乎面经"),
    ("360", "360面经"),
    ("OPPO", "OPPO面经"),
    ("vivo", "vivo面经"),
]

# Pacing — keep gentle to avoid detection / account ban
MIN_DELAY_SEC = 3.0
MAX_DELAY_SEC = 8.0
SCROLL_DELAY_SEC = 1.5
SEARCH_URL = "https://www.xiaohongshu.com/search_result/?keyword={kw}&type=51"
HOME_URL = "https://www.xiaohongshu.com"
