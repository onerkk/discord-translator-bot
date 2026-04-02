"""
翻譯小助手 — Discord Bot
Ported from LINE translator bot (Walsin Lihwa / 華新麗華 鹽水廠)
"""
import os
import re
import json
import logging
import urllib.request
import urllib.parse
import time
import asyncio
import io

import discord
from discord import app_commands
from discord.ext import commands
from openai import OpenAI
from aiohttp import web

# ─── Config ─────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("discord_bot")

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")

oai = OpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

# ─── Per-channel settings ───────────────────────────────
channel_settings = {}       # {channel_id: True/False} translation on/off
channel_target_lang = {}    # {channel_id: "id"/"en"/...}
channel_skip_users = {}     # {channel_id: set(user_ids)}

# Translation cache
translation_cache = {}
CACHE_MAX_SIZE = 500
CACHE_TTL = 3600

# ─── Language constants ─────────────────────────────────
LANG_FLAGS = {
    "zh": "\U0001f1f9\U0001f1fc", "id": "\U0001f1ee\U0001f1e9",
    "en": "\U0001f1ec\U0001f1e7", "vi": "\U0001f1fb\U0001f1f3",
    "th": "\U0001f1f9\U0001f1ed", "ja": "\U0001f1ef\U0001f1f5",
    "ko": "\U0001f1f0\U0001f1f7", "ms": "\U0001f1f2\U0001f1fe",
    "tl": "\U0001f1f5\U0001f1ed",
}
LANG_NAMES = {
    "zh": "Traditional Chinese", "id": "Indonesian", "en": "English",
    "vi": "Vietnamese", "th": "Thai", "ja": "Japanese",
    "ko": "Korean", "ms": "Malay", "tl": "Filipino/Tagalog",
}
LANG_NAMES_ZH = {
    "id": "印尼文", "en": "英文", "vi": "越南文", "th": "泰文",
    "ja": "日文", "ko": "韓文", "ms": "馬來文", "tl": "菲律賓文",
}
VALID_TARGETS = ["id", "en", "vi", "th", "ja", "ko", "ms", "tl"]

# ─── Hard replacement tables ────────────────────────────
ZH_TO_ID_HARD = {
    "爐號標籤": "label heat number", "爐號": "heat number",
    "無心研磨": "centerless grinding", "光輝退火爐": "furnace bright annealing",
    "光輝退火": "bright annealing", "退火爐": "tungku annealing",
    "過帳": "input data ke sistem", "放行": "release data",
    "殺光痕": "bekas grinding mark", "車刀痕": "bekas pisau bubut",
    "砂光痕": "bekas sanding mark", "軋輥印痕": "bekas roll mark",
    "環狀擦傷": "goresan melingkar", "表粗": "surface roughness",
    "偏小": "under size", "偏大": "over size", "風險批": "lot berisiko",
    "走ET檢測": "jalankan pengujian ET", "開立重工": "buat work order rework",
    "不允收": "pelanggan tidak terima",
    "矯直機": "mesin straightening", "壓光機": "mesin press polish",
    "砂光機": "mesin sanding", "拋光機": "mesin polishing",
    "眼模": "die/cetakan", "引拔座": "drawing bench", "皮膜槽": "coating tank",
    "氣壓缸": "silinder pneumatik", "安全圍籬": "safety fence",
    "集塵設備": "dust collector", "計長器": "length counter", "冷水機": "chiller",
    "馬蹄環": "shackle", "吊掛物": "beban gantung", "護罩": "pelindung mesin",
    "interlock": "pengunci keamanan", "標籤機": "mesin label",
    "品保": "QC", "儲運": "bagian gudang", "生計": "production planning",
    "業務": "bagian sales", "營業": "bagian sales", "人事": "HRD",
    "處長": "kepala divisi", "稼動率": "utilization rate", "線速": "kecepatan lini",
    "速差": "selisih kecepatan", "主機手": "operator utama", "印勞": "pekerja Indonesia",
    "在製品管制表": "tabel kontrol WIP",
    "套紙管": "pasang tabung kertas", "太空包": "jumbo bag",
    "噴漆罐": "kaleng spray", "木箱": "kotak kayu", "櫃子": "kontainer",
    "允收": "toleransi terima", "訂尺": "panjang pesanan", "短尺": "ukuran pendek",
    "異型棒": "batang bentuk khusus", "遞延單": "order ditunda", "急單": "order urgent",
    "不擋非本月": "order bukan bulan ini boleh masuk gudang", "不擋": "tidak dibatasi",
    "溢量": "kelebihan produksi", "併包": "gabung packing",
    "出貨差": "kekurangan pengiriman",
    "忘卡補": "input lewat sistem lupa kartu", "造冊": "buat daftar absensi",
    "班股": "rapat shift", "堆高機複訓": "pelatihan ulang forklift",
    "天車複訓": "pelatihan ulang crane", "扣績效": "potong penilaian kinerja",
    "劣項": "pelanggaran", "納入劣項": "dicatat pelanggaran",
    "提報懲處": "laporkan untuk sanksi", "三定": "3 tetap",
    "不要物": "barang tidak terpakai", "被釘": "kena tegur",
    "綠卡": "kartu hijau",
    "煙蒂": "puntung rokok", "檳榔渣": "sisa pinang", "廚餘": "sisa makanan",
    "漏油": "bocor oli", "積水": "genangan air", "粉塵": "debu",
    "感溫": "terima kasih", "有夠": "sangat", "母湯": "jangan",
}

ID_POST_FIX = {
    "nomor panas": "heat number", "label nomor panas": "label heat number",
    "nomor tungku": "heat number", "label nomor tungku": "label heat number",
    "nomor oven": "heat number", "label nomor oven": "label heat number",
    "paket datang ke": "kalau ada packing untuk",
    "saat paket datang ke": "kalau ada packing untuk",
    "Mohon diperhatikan saat paket datang ke": "Nanti kalau ada packing untuk",
    "Mohon diperhatikan saat kalau ada packing untuk": "Nanti kalau ada packing untuk",
    "tiga meter di atas enam meter": "batang 3 meter ditaruh di atas batang 6 meter",
    "Tiga meter di atas enam meter": "Batang 3 meter ditaruh di atas batang 6 meter",
    "3 meter di atas 6 meter": "batang 3 meter ditaruh di atas batang 6 meter",
    "jaminan kualitas": "QC", "penjaminan mutu": "QC",
    "panggilan nama": "inspeksi pengawas", "absen nama": "inspeksi pengawas",
    "roll call": "inspeksi pengawas",
    "suhu perasaan": "terima kasih", "merasakan suhu": "terima kasih",
    "Polymetal": "寶麗金屬", "Bao Li Metal": "寶麗金屬", "Bao Li Logam": "寶麗金屬",
    "Changzhou Zhongshan": "常州眾山", "Da Shun": "大順", "Da Cheng": "大成",
    "Bei Ze": "北澤", "Hong Yun": "鴻運", "Tian Hua Rong": "田華榕",
    "Jia Dong": "佳東",
    "bagian operasional": "bagian sales", "operasional perlu": "sales perlu",
}

# ─── Storage data (embedded) ────────────────────────────
_STORAGE_JSON = '{"6C422209": [["<=3200", "EH28"], [">4200", "EG38"], [">3200<=4200", "EH26"]], "ABE": [[">3200<=4200", "EG14"], ["<=3200", "EH28"], [">4200", "EG34"]], "AIK": [[">3200<=4200", "EG14"], [">4200", "EH33"], ["<=3200", "EH28"]], "ALCONIX JP": [["<=3200", "EG14"], [">4200", "EH33"], [">3200<=4200", "EG14"]], "AMERICAN STAINLESS": [[">3200<=4200", "EG14"], [">4200", "EG34"], ["<=3200", "EH28"]], "AMS": [[">3200<=4200", "EG14"], [">4200", "EG34"], ["<=3200", "EH28"]], "ANCHOR": [[">3200<=4200", "EG14"], ["<=3200", "EH28"], [">4200", "EG34"]], "ANIL METALS": [[">3200<=4200", "EG14"], ["<=3200", "EH28"], [">4200", "EH33"]], "APEX METAL": [["<=3200", "EH28"], [">4200", "EH33"], [">3200<=4200", "EG14"]], "AWACS": [[">3200<=4200", "EG14"], [">4200", "EG34"], ["<=3200", "EH28"]], "B&B": [[">4200", "EH33"], ["<=3200", "EH22"], [">3200<=4200", "EG14"]], "B&J": [["<=3200", "EC40"], [">4200", "EC40"], [">3200<=4200", "EC45"]], "BOBCO": [["<=3200", "EH28"], [">3200<=4200", "EG14"], [">4200", "EH34"]], "BOLLINGHAUS": [[">3200<=4200", "EC43"], ["<=3200", "EC43"], [">4200", "EC43"]], "CA-ASD": [[">4200", "EH11"], ["<=3200", "EH12"], [">3200<=4200", "EH12"]], "CA-AUSTRAL": [[">3200<=4200", "EH12"], ["<=3200", "EH12"], [">4200", "EH11"]], "CA-DALSTEEL": [[">4200", "EH11"], ["<=3200", "EH12"], [">3200<=4200", "EH12"]], "CA-FLETCHER": [[">3200<=4200", "EH12"], [">4200", "EH11"], ["<=3200", "EH28"]], "CA-M&S": [["<=3200", "EH12"], [">3200<=4200", "EH12"], [">4200", "EH11"]], "CA-MICO": [["<=3200", "EH12"], [">3200<=4200", "EH12"], [">4200", "EH11"]], "CA-MIDWAY": [["<=3200", "EH12"], [">3200<=4200", "EH12"], [">4200", "EH11"]], "CA-S&T": [["<=3200", "EH12"], [">3200<=4200", "EH12"], [">4200", "EH11"]], "CA-VAN LEEUWEN": [["<=3200", "EH12"], [">4200", "EH11"], [">3200<=4200", "EH12"]], "CA-VES": [["<=3200", "EH12"], [">3200<=4200", "EH12"], [">4200", "EH11"]], "CA-VULCAN": [[">4200", "EH11"], ["<=3200", "EH12"], [">3200<=4200", "EH12"]], "CA-VULCAN NZ": [["<=3200", "EH12"], [">3200<=4200", "EH12"], [">4200", "EH11"]], "CA-WAKEFIELD": [[">4200", "EH11"], [">3200<=4200", "EH12"], ["<=3200", "EH12"]], "CAMELLIA": [[">3200<=4200", "EG14"], ["<=3200", "EH28"], [">4200", "EG34"]], "CASTLE": [[">3200<=4200", "EH12"], ["<=3200", "EH28"], [">4200", "EH11"]], "CHANDAN": [[">3200<=4200", "EG14"], ["<=3200", "EH28"], [">4200", "EH33"]], "CHANG HSIN": [["<=3200", "EH28"], [">3200<=4200", "EG14"], [">4200", "EG34"]], "CONTINENTAL": [[">3200<=4200", "EG14"], [">4200", "EG34"], ["<=3200", "EH28"]], "DACAPO": [["<=3200", "EH22"], [">3200<=4200", "EG14"], [">4200", "EG34"]], "DK METAL": [[">3200<=4200", "EG14"], [">4200", "EH33"], ["<=3200", "EH28"]], "ESTEELINDO": [[">3200<=4200", "EG14"], [">4200", "EH33"], ["<=3200", "EH28"]], "EURO INOX": [[">3200<=4200", "EG14"], [">4200", "EH33"], ["<=3200", "EH28"]], "FIX": [["<=3200", "EH28"], [">4200", "EG34"], [">3200<=4200", "EG14"]], "FORTUNE METAL": [[">3200<=4200", "EG14"], ["<=3200", "EH28"], [">4200", "EG34"]], "GD METAL": [[">3200<=4200", "EG14"], [">4200", "EH33"], ["<=3200", "EH28"]], "GLH": [[">4200", "EG34"], ["<=3200", "EH28"], [">3200<=4200", "EG14"]], "GLOBAL STAINLESS": [[">3200<=4200", "EG14"], ["<=3200", "EH28"], [">4200", "EH33"]], "GP SYRMA": [[">3200<=4200", "EG14"], ["<=3200", "EH28"], [">4200", "EG34"]], "H.Y.S.": [["<=3200", "EH22"], [">3200<=4200", "EG14"], [">4200", "EH33"]], "HANSAE": [[">3200<=4200", "EG14"], ["<=3200", "EH28"], [">4200", "EH33"]], "HIDAYAT": [[">3200<=4200", "EG14"], ["<=3200", "EH28"], [">4200", "EH33"]], "ISTANA KARANG LAUT": [[">3200<=4200", "EG14"], ["<=3200", "EH28"], [">4200", "EH33"]], "JAYESH": [[">3200<=4200", "EG14"], ["<=3200", "EH28"], [">4200", "EH33"]], "JIGNESH": [[">3200<=4200", "EG14"], ["<=3200", "EH28"], [">4200", "EH33"]], "KANGRUI": [[">3200<=4200", "EG14"], [">4200", "EG34"], ["<=3200", "EH28"]], "KARTHIK": [[">3200<=4200", "EG14"], ["<=3200", "EH28"], [">4200", "EH33"]], "KJ": [[">3200<=4200", "EG14"], [">4200", "EH33"], ["<=3200", "EH28"]], "LEMONA": [["<=3200", "EH28"], [">3200<=4200", "EG14"], [">4200", "EH33"]], "LOGAM MAS": [[">3200<=4200", "EG14"], [">4200", "EH33"], ["<=3200", "EH28"]], "MANGAL": [[">3200<=4200", "EG14"], [">4200", "EH33"], ["<=3200", "EH28"]], "METALINOX": [[">3200<=4200", "EG14"], [">4200", "EG34"], ["<=3200", "EH28"]], "MICROSTEEL": [[">3200<=4200", "EG14"], ["<=3200", "EH28"], [">4200", "EG34"]], "PANCHMAHAL": [[">3200<=4200", "EG14"], ["<=3200", "EH28"], [">4200", "EH33"]], "PLUTUS": [[">3200<=4200", "EG14"], ["<=3200", "EH28"], [">4200", "EH33"]], "PT.COGNE": [[">3200<=4200", "EC43"], ["<=3200", "EC43"], [">4200", "EC43"]], "SAMRAT": [[">3200<=4200", "EG14"], ["<=3200", "EH28"], [">4200", "EH33"]], "SAMWON": [[">3200<=4200", "EG14"], ["<=3200", "EH28"], [">4200", "EH33"]], "SHANDONG GUANGDA": [[">3200<=4200", "EG14"], [">4200", "EH33"], ["<=3200", "EH28"]], "SHREE AMBIKA": [[">3200<=4200", "EG14"], [">4200", "EH33"], ["<=3200", "EH28"]], "STEELINC": [[">3200<=4200", "EG14"], [">4200", "EG34"], ["<=3200", "EH28"]], "SUNGEUN": [[">3200<=4200", "EG14"], ["<=3200", "EH28"], [">4200", "EG34"]], "SUPRA": [[">3200<=4200", "EG14"], ["<=3200", "EH28"], [">4200", "EH33"]], "TATASTEEL": [[">3200<=4200", "EG14"], ["<=3200", "EH28"], [">4200", "EH33"]], "TCI": [["<=3200", "EC43"], [">4200", "EC43"], [">3200<=4200", "EC43"]], "THREE STAR": [[">3200<=4200", "EG14"], [">4200", "EH33"], ["<=3200", "EH28"]], "TOKYO STAINLESS": [[">3200<=4200", "EG14"], [">4200", "EH33"], ["<=3200", "EH28"]], "TOPGAIN": [["<=3200", "EH28"], [">3200<=4200", "EG14"], [">4200", "EH33"]], "VIRAJ": [[">3200<=4200", "EG14"], ["<=3200", "EH28"], [">4200", "EH33"]], "ZHEJIANG": [[">3200<=4200", "EG14"], [">4200", "EH33"], ["<=3200", "EH28"]], "三寶": [[">3200<=4200", "EH78"], ["<=3200", "EH79"], [">4200", "EG38"]], "三陽": [[">3200<=4200", "EH78"], ["<=3200", "EH79"], [">4200", "EG38"]], "上暉": [[">3200<=4200", "EH78"], ["<=3200", "EH79"], [">4200", "EG38"]], "久鑫": [["<=3200", "EH79"], [">4200", "EG38"], [">3200<=4200", "EH78"]], "元台": [[">3200<=4200", "EH78"], [">4200", "EG38"], ["<=3200", "EH79"]], "全聯": [[">3200<=4200", "EH78"], ["<=3200", "EH79"], [">4200", "EG38"]], "六星": [["<=3200", "EH79"], [">3200<=4200", "EH78"], [">4200", "EG38"]], "冠升": [["<=3200", "EH79"], [">3200<=4200", "EH78"], [">4200", "EG38"]], "利泓": [[">3200<=4200", "EH78"], ["<=3200", "EH79"], [">4200", "EG38"]], "加倍力": [[">3200<=4200", "EH78"], ["<=3200", "EH79"], [">4200", "EG38"]], "北澤": [["<=3200", "EH79"], [">3200<=4200", "EH78"], [">4200", "EG38"]], "協和": [[">3200<=4200", "EH78"], ["<=3200", "EH79"], [">4200", "EG38"]], "協奇": [[">3200<=4200", "EH78"], ["<=3200", "EH79"], [">4200", "EG38"]], "台芝": [[">3200<=4200", "EH78"], ["<=3200", "EH79"], [">4200", "EG38"]], "右勝": [[">3200<=4200", "EH78"], ["<=3200", "EH79"], [">4200", "EG38"]], "名威": [[">3200<=4200", "EH78"], ["<=3200", "EH79"], [">4200", "EG38"]], "和鍵": [[">3200<=4200", "EH78"], ["<=3200", "EH79"], [">4200", "EG38"]], "唐榮": [["<=3200", "EC47"], [">3200<=4200", "EC40"], [">4200", "EC40"]], "嘉泰": [["<=3200", "EH79"], [">3200<=4200", "EH78"], [">4200", "EG38"]], "四維": [[">3200<=4200", "EH78"], ["<=3200", "EH79"], [">4200", "EG38"]], "堡辰": [[">3200<=4200", "EH78"], ["<=3200", "EH79"], [">4200", "EG38"]], "大成": [["<=3200", "EH79"], [">3200<=4200", "EH78"], [">4200", "EG38"]], "大洋": [[">3200<=4200", "EH78"], ["<=3200", "EH79"], [">4200", "EG38"]], "大順": [[">3200<=4200", "EH78"], ["<=3200", "EH79"], [">4200", "EG38"]], "天基": [[">3200<=4200", "EH78"], ["<=3200", "EH79"], [">4200", "EG38"]], "奧森": [["<=3200", "EH79"], [">3200<=4200", "EH78"], [">4200", "EG38"]], "寶穎": [[">3200<=4200", "EH78"], [">4200", "EG38"], ["<=3200", "EH79"]], "巨昌": [["<=3200", "EH79"], [">3200<=4200", "EH78"], [">4200", "EG38"]], "常州眾山": [[">3200<=4200", "EG14"], [">4200", "EH33"], ["<=3200", "EH28"]], "廉錩": [["<=3200", "EH79"], [">3200<=4200", "EH78"], [">4200", "EG38"]], "弘森": [["<=3200", "EH79"], [">4200", "EG38"], [">3200<=4200", "EH78"]], "志盛": [["<=3200", "EH79"], [">3200<=4200", "EH78"], [">4200", "EG38"]], "慶達": [["<=3200", "EH79"], [">3200<=4200", "EH78"], [">4200", "EG38"]], "擎億": [["<=3200", "EH79"], [">3200<=4200", "EH78"], [">4200", "EG38"]], "新光": [["<=3200", "EH79"], [">3200<=4200", "EH78"], [">4200", "EG38"]], "旗勝": [[">3200<=4200", "EH78"], [">4200", "EG38"], ["<=3200", "EH79"]], "明憲": [[">3200<=4200", "EH78"], ["<=3200", "EH79"], [">4200", "EG38"]], "普利擎": [[">3200<=4200", "EH78"], ["<=3200", "EH79"], [">4200", "EG38"]], "永吉": [["<=3200", "EH79"], [">3200<=4200", "EH78"], [">4200", "EG38"]], "津展": [[">3200<=4200", "EH78"], ["<=3200", "EH79"], [">4200", "EG38"]], "洪福": [["<=3200", "EH79"], [">3200<=4200", "EH78"], [">4200", "EG38"]], "源盛傑": [["<=3200", "EH79"], [">3200<=4200", "EH78"], [">4200", "EG38"]], "漢翊": [["<=3200", "EH79"], [">3200<=4200", "EH78"], [">4200", "EG38"]], "百堅": [[">3200<=4200", "EH78"], ["<=3200", "EH79"], [">4200", "EG38"]], "皇銘": [[">3200<=4200", "EH27"], ["<=3200", "EH27"], [">4200", "EG38"]], "盛英": [[">3200<=4200", "EH78"], ["<=3200", "EH79"], [">4200", "EG38"]], "知行": [[">3200<=4200", "EH78"], ["<=3200", "EH79"], [">4200", "EG38"]], "磐石": [["<=3200", "EH79"], [">3200<=4200", "EH78"], [">4200", "EG38"]], "誼山": [["<=3200", "EH29"], [">3200<=4200", "EH78"], [">4200", "EH38"]], "頭份": [[">4200", "EG38"], [">3200<=4200", "EH78"], ["<=3200", "EH79"]], "優普洛": [["<=3200", "EH79"], [">3200<=4200", "EH78"], [">4200", "EG38"]], "營三備庫(內)": [[">3200<=4200", "EC40"], ["<=3200", "EC47"], [">4200", "EC40"]], "營三備庫(外)": [[">3200<=4200", "EC40"], [">4200", "EC40"], ["<=3200", "EC47"]], "營業庫存": [[">4200", "EH99"], ["<=3200", "EH99"], [">3200<=4200", "EH99"]], "環友": [[">3200<=4200", "EH78"], ["<=3200", "EH79"], [">4200", "EG38"]], "聯岱": [[">4200", "EG38"], ["<=3200", "EH79"], [">3200<=4200", "EH78"]], "聯祥": [[">3200<=4200", "EH78"], ["<=3200", "EH79"], [">4200", "EG38"]], "邁達斯": [[">4200", "EG38"], ["<=3200", "EH79"], [">3200<=4200", "EH78"]], "鴻運": [[">3200<=4200", "EH27"], ["<=3200", "EH27"], [">4200", "EG38"]], "雙和": [[">3200<=4200", "EG14"], ["<=3200", "EH26"], [">4200", "EG34"]], "麒譯": [["<=3200", "EH79"], [">4200", "EG38"], [">3200<=4200", "EH78"]], "町洋": [["<=3200", "EH79"], [">4200", "EG38"], [">3200<=4200", "EH78"]], "晟田": [["<=3200", "EH79"], [">4200", "EG38"], [">3200<=4200", "EH78"]], "畯圓": [["<=3200", "EH19"], [">4200", "EG38"], [">3200<=4200", "EH78"]], "鐿順發": [["<=3200", "EH79"], [">4200", "EG38"], [">3200<=4200", "EH78"]], "鑫誠鐵材": [["<=3200", "EH79"], [">4200", "EG38"], [">3200<=4200", "EH78"]], "恒耀": [["<=3200", "EH79"], [">4200", "EG38"], [">3200<=4200", "EH78"]], "暉": [[">3200<=4200", "EH78"], ["<=3200", "EH79"], [">4200", "EG38"]], "頂": [[">3200<=4200", "EH78"], ["<=3200", "EH79"], [">4200", "EG38"]]}'
STORAGE_LOOKUP = json.loads(_STORAGE_JSON)

# Try loading external storage_data.json
_storage_json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "storage_data.json")
if os.path.exists(_storage_json_path):
    try:
        with open(_storage_json_path, "r", encoding="utf-8") as _f:
            STORAGE_LOOKUP = json.load(_f)
            logger.info("Loaded storage_data.json: %d customers", len(STORAGE_LOOKUP))
    except Exception as _e:
        logger.warning("Failed to load storage_data.json: %s", _e)

EXTRA_CUSTOMERS = [
    "寶麗金屬", "田華榕", "蘋果", "賽利金屬", "盛昌遠", "曜麟",
    "LOTUS", "LOTUS METAL", "shinko", "wing keung",
]
CUSTOMER_NAMES = sorted(
    list(set(list(STORAGE_LOOKUP.keys()) + EXTRA_CUSTOMERS)),
    key=lambda x: -len(x)
)


# ─── Mention handling (Discord style) ──────────────────
def extract_mentions_discord(text):
    """Extract Discord <@id> mentions."""
    return re.findall(r'<@!?\d+>', text)


def protect_mentions(text):
    mentions = extract_mentions_discord(text)
    protected = text
    placeholders = {}
    for i, m in enumerate(mentions):
        ph = f"__MENTION_{i}__"
        placeholders[ph] = m
        protected = protected.replace(m, ph, 1)
    return protected, placeholders


def restore_mentions(text, placeholders):
    restored = text or ""
    for ph, original in placeholders.items():
        idx = ph.replace("__MENTION_", "").replace("__", "")
        variants = [ph, ph.replace("_", " "), f"MENTION_{idx}", f"MENTION {idx}",
                    f"__MENTION {idx}__", f"[[MENTION_{idx}]]"]
        for v in variants:
            restored = restored.replace(v, original)
    missing = [orig for orig in placeholders.values() if orig not in restored]
    if missing:
        restored = " ".join(missing) + " " + restored
    return restored.strip()


# ─── Language detection ─────────────────────────────────
def has_chinese(text):
    return len(re.findall(r'[\u4e00-\u9fff]', text)) >= 2

def has_japanese(text):
    return (len(re.findall(r'[\u3040-\u309f]', text)) + len(re.findall(r'[\u30a0-\u30ff]', text))) >= 2

def has_korean(text):
    return len(re.findall(r'[\uac00-\ud7af]', text)) >= 2

def has_thai(text):
    return len(re.findall(r'[\u0e00-\u0e7f]', text)) >= 2

def has_vietnamese(text):
    vi_special = re.findall(r'[\u01a0\u01a1\u01af\u01b0\u0110\u0111]', text)
    vi_chars = re.findall(r'[\u00e0-\u00ff\u1ea0-\u1ef9]', text.lower())
    words = text.lower().split()
    vi_markers = {'cua','nhung','trong','duoc','khong','nhu','mot','toi','ban','anh','chi','em',
                  'la','va','cac','cho','voi','tai','nay','khi','con','roi','lam','biet','muon',
                  'den','di','xin','cam','chao','dep','ngon','tot','xau'}
    marker_count = sum(1 for w in words if w in vi_markers)
    if len(vi_special) >= 1:
        return True
    if len(vi_chars) >= 3 and marker_count >= 1:
        return True
    return False

def has_indonesian(text):
    if has_chinese(text) or has_thai(text) or has_korean(text) or has_japanese(text):
        return False
    words = re.findall(r'[a-zA-Z]+', text.lower())
    if len(words) < 2:
        return False
    id_words = {
        'yang','dan','ini','itu','ada','untuk','dengan','dari','tidak','akan','sudah','bisa',
        'juga','saya','kami','kita','mereka','dia','apa','bagaimana','kenapa','kapan','dimana',
        'siapa','belum','sedang','harus','boleh','mau','ingin','bukan','jangan','tolong',
        'terima','kasih','selamat','pagi','siang','sore','malam','baik','bagus','benar',
        'salah','besar','kecil','makan','minum','tidur','kerja','pulang','pergi','rumah',
        'kantor','uang','harga','berapa','banyak','sedikit','semua','karena','tetapi','tapi',
        'atau','jika','kalau','sampai','masih','lagi','saja','dulu','nanti','sekarang',
        'hari','minggu','bulan','tahun','gak','nggak','udah','gimana','dong','sih','nih',
        'kok','yuk','ayo','banget','orang','baru','lembur','cuti','gaji','minta','ambil',
        'kirim','tunggu','cepat','lambat','susah','gampang','senang','sedih','marah',
        'takut','capek','lapar','haus','sakit','sehat','di','ke','jam','ruang','baca',
        'soal','ujian','terakhir','kamu','jadi','harap','ukur','secara','manual','rusak',
        'saat','mohon','pakai',
    }
    id_count = sum(1 for w in words if w in id_words)
    return id_count >= 2

def has_english(text):
    if has_chinese(text) or has_thai(text) or has_korean(text) or has_japanese(text):
        return False
    words = re.findall(r'[a-zA-Z]+', text.lower())
    if len(words) < 2:
        return False
    en_words = {
        'the','is','are','was','were','have','has','had','do','does','did','will','would',
        'can','could','should','shall','may','might','must','been','being','what','where',
        'when','who','how','why','which','this','that','these','those','with','from',
        'about','into','through','after','before','between','under','over','again','then',
        'here','there','very','just','also','not','but','and','for','all','each','every',
        'both','few','more','most','other','some','such','only','same','than','too',
    }
    id_words_check = {
        'yang','dan','ini','itu','ada','untuk','dengan','dari','tidak','sudah','bisa',
        'saya','kami','mereka','apa','bagaimana','kenapa','belum','harus','boleh','mau',
        'jangan','tolong','terima','kasih','selamat','pagi','siang','sore','malam',
    }
    en_count = sum(1 for w in words if w in en_words)
    id_count = sum(1 for w in words if w in id_words_check)
    return en_count > id_count and en_count >= 2

def detect_language(text):
    clean = re.sub(r'<@!?\d+>', ' ', text)
    clean = re.sub(r'https?://\S+', ' ', clean)
    clean = clean.strip()
    if not clean:
        return None
    if has_japanese(clean) and not has_chinese(clean):
        return "ja"
    if has_korean(clean):
        return "ko"
    if has_thai(clean):
        return "th"
    if has_chinese(clean):
        latin_words = re.findall(r'[a-zA-Z]+', clean.lower())
        id_words = {
            'yang','dan','ini','itu','ada','untuk','dengan','dari','tidak','akan','sudah',
            'bisa','juga','saya','kami','kita','mereka','dia','apa','bagaimana','kenapa',
            'kapan','dimana','siapa','belum','sedang','harus','boleh','mau','ingin','bukan',
            'jangan','tolong','terima','kasih','selamat','pagi','siang','sore','malam',
            'baik','bagus','benar','salah','besar','kecil','makan','minum','tidur','kerja',
            'pulang','pergi','rumah','kantor','uang','harga','berapa','banyak','sedikit',
            'semua','karena','tetapi','tapi','atau','jika','kalau','sampai','masih','lagi',
            'saja','dulu','nanti','sekarang','hari','minggu','bulan','tahun','gak','nggak',
            'udah','gimana','dong','sih','nih','kok','yuk','ayo','banget','orang','baru',
            'lembur','cuti','gaji','minta','ambil','kirim','tunggu','cepat','lambat',
            'susah','gampang','senang','sedih','marah','takut','capek','lapar','haus',
            'sakit','sehat','di','ke','jam','ruang','baca','soal','ujian','terakhir',
            'kamu','jadi','harap','ukur','secara','manual','rusak','saat','mohon','pakai',
        }
        id_count = sum(1 for w in latin_words if w in id_words)
        if id_count >= 2:
            return "id"
        return "zh"
    if has_vietnamese(clean):
        return "vi"
    if has_indonesian(clean):
        return "id"
    if has_english(clean):
        return "en"
    return None


# ─── Translation pipeline ──────────────────────────────
def pre_replace_zh(text):
    result = text
    cust_ph = {}
    for i, name in enumerate(CUSTOMER_NAMES):
        if name in result:
            ph = f"__CUST_{i}__"
            cust_ph[ph] = name
            result = result.replace(name, ph)
    for zh, replacement in sorted(ZH_TO_ID_HARD.items(), key=lambda x: -len(x[0])):
        if zh in result:
            result = result.replace(zh, f"[{replacement}]")
    return result, cust_ph

def restore_customers(text, cust_ph):
    if not text or not cust_ph:
        return text
    result = text
    for ph, name in cust_ph.items():
        idx = ph.replace("__CUST_", "").replace("__", "")
        variants = [ph, ph.replace("_", " "), f"CUST_{idx}", f"CUST {idx}",
                    f"__CUST {idx}__", f"[CUST_{idx}]"]
        for v in variants:
            if v in result:
                result = result.replace(v, name)
    result = re.sub(r'__CUST_(\d+)__',
                    lambda m: cust_ph.get(f"__CUST_{m.group(1)}__", m.group(0)), result)
    return result

def post_fix_translation(text):
    if not text:
        return text
    result = text
    for wrong, correct in sorted(ID_POST_FIX.items(), key=lambda x: -len(x[0])):
        result = result.replace(wrong, correct)
    result = re.sub(r'\[([a-zA-Z /&]+)\]', r'\1', result)
    result = re.sub(r'\s{2,}', ' ', result).strip()
    return result

def contains_source_script(text, src):
    cleaned = re.sub(r'__MENTION_\d+__', ' ', text or '')
    cleaned = re.sub(r'__CUST_\d+__', ' ', cleaned)
    for name in CUSTOMER_NAMES:
        if name in cleaned:
            cleaned = cleaned.replace(name, ' ')
    patterns = {"zh": r'[\u4e00-\u9fff]', "ja": r'[\u3040-\u30ff\u4e00-\u9fff]',
                "ko": r'[\uac00-\ud7af]', "th": r'[\u0e00-\u0e7f]'}
    pattern = patterns.get(src)
    if not pattern:
        return False
    return len(re.findall(pattern, cleaned)) >= 2

def is_translation_valid(result, src, tgt):
    if not result or not result.strip():
        return False
    if src != tgt and contains_source_script(result, src):
        return False
    return True

def build_system_prompt(extra_rule=""):
    return (
        "You are a professional translator for a stainless steel factory (Walsin Lihwa/華新麗華, Yanshui plant) work group chat. "
        "This factory produces stainless steel bars, wire rods, peeled bars, cold-drawn bars using processes like rolling, annealing, pickling, peeling, cold drawing, and centerless grinding. "
        "This is a group with Taiwanese managers and Indonesian migrant workers operating centerless grinding (無心研磨) equipment. "
        "CRITICAL RULES: "
        "1. NEVER translate @mentions and NEVER translate or romanize person names. Keep all Chinese names in ORIGINAL CHINESE CHARACTERS. "
        "For example: 徐嘉騰 stays as 徐嘉騰, NOT Xu Jiateng. 陳弘林 stays as 陳弘林, NOT Chen Honglin. "
        "Chinese nicknames for people must stay unchanged. Do NOT translate them literally. "
        "2. Any text like __MENTION_0__, __MENTION_1__ etc are placeholders - keep them exactly as is. "
        "3. Translate all other content completely and naturally like real people talk at work. Use casual daily language. "
        "4. Indonesian slang: gak=tidak, udah=sudah, gimana=bagaimana, bgt=banget, org=orang, yg=yang, tdk=tidak, dg=dengan, krn=karena, blm=belum, hrs=harus, bs=bisa, lg=lagi, gw=saya, lu=kamu. "
        "5. TAIWANESE MANDARIN COLLOQUIAL (very important): "
        "乾/干=aduh/astaga, 靠=astaga/waduh, 幹=sial/buset, 傻眼=gak percaya, 扯/誇張=keterlaluan, 笑死=ngakak, 氣死=kesel banget, 累死=capek banget, "
        "啦=lah/dong, 喔/哦=ya/lho, 耶=dong/nih, 嘛=dong/kan, 蛤=hah?/apa?, 厚=ya kan, "
        "醬/降=begitu/gitu(=這樣), 母湯=jangan/gak boleh(=不要), 超/有夠=banget(=非常), 感溫=terima kasih(台語感恩), "
        "CRITICAL: Taiwanese rhetorical questions SUGGEST doing something: 需不需要X=perlu X gak nih(suggesting X should be done), 要不要X=gimana kalau X, 還在X=masih X(often implies criticism). "
        "搞什麼=ngapain sih, 搞定=beres, 人咧=orangnya mana, 怎麼搞的=kenapa bisa begini, 出包=ada masalah, 先這樣=segitu dulu ya, 再說=nanti aja, "
        "X到不行/X得要死/X到爆=X banget, 怎麼這麼X=kok X banget, 有夠X=X banget, "
        "ㄏㄏ=haha, QQ=sedih, 3Q=terima kasih, GG=tamat, XD=haha, @@=bingung. "
        "6. Target Traditional Chinese = Taiwan style, not mainland. "
        "7. Target Indonesian = simple clear daily language for factory workers. "
        "8. Context: factory work - shifts, overtime, orders, tasks, meals, breaks, meetings, exams. "
        "9. FACTORY VOCABULARY: "
        "【製程/Process】無心研磨=centerless grinding, 研磨=grinding, 砂輪=batu gerinda, 調整輪=roda pengatur, 刀板=work rest blade, 冷卻液=cairan pendingin, "
        "不鏽鋼=stainless steel, 棒鋼=steel bar, 盤元=wire rod, 削皮棒=peeled bar, 冷精棒=cold-drawn bar, "
        "熱軋=hot rolling, 退火=annealing, 酸洗=pickling, 削皮=peeling, 冷抽=cold drawing, "
        "鋼種=jenis baja, PMI=uji material, 來料=material masuk, 棒材=batang baja, 混料=tercampur material(SERIOUS), 料號=nomor material, "
        "拋光=polishing, 粗拋=rough polishing, 噴漆=spray paint, 洗料=cuci material, "
        "倒角=chamfer, 修磨=repair grinding, 壓光=press polish, 矯直=straightening, 精整=finishing, AP=mesin finishing, "
        "光輝退火=bright annealing, 回爐=kirim kembali ke furnace, "
        "側磨=side grinding(DILARANG/prohibited), 不可側磨=dilarang side grinding, "
        "【班次/出勤】點名=ada pengawas yang datang(inspection, NOT roll call), 早班=shift pagi, 夜班=shift malam, 中班=shift siang, "
        "加班=lembur, 請假=izin, 病假=izin sakit, 事假=izin pribadi, 特休=cuti tahunan, "
        "【設備】天車=overhead crane, 台車=trolley, 吊秤=timbangan gantung, 馬蹄環=shackle, "
        "稼動率=utilization rate, 線速=line speed, 主機手=operator utama, 印勞=pekerja Indonesia, "
        "【包裝】套紙管=pasang tabung kertas, 入庫=masuk gudang, 櫃子=kontainer, 木箱=kotak kayu, "
        "把=bundel, 捆=bundel/ikat, 支/根=batang, 批=lot/batch, "
        "包(verb)=packing, 秤重=timbang, 貼標=tempel label, "
        "【訂單】允收=jumlah yang boleh diterima, 訂尺=panjang sesuai pesanan, 爐號=heat number, "
        "不擋=tidak dibatasi(ALLOWED), 不擋非本月=order bukan bulan ini BOLEH masuk gudang, "
        "溢量=kelebihan produksi, 併包=gabung packing, 出貨差=kekurangan pengiriman, "
        "過帳=input data ke sistem, 放行=release data, "
        "【品質】品保=QC, 客訴=komplain pelanggan, 偏小=under size, 偏大=over size, 表粗=surface roughness, "
        "開立重工=buat WO rework, 風險批=lot berisiko, "
        "【部門】業務=sales, 營業=sales, 生計=production planning, 品保=QC, 儲運=gudang&logistik, 人事=HRD, "
        "處長=kepala divisi, "
        "10. CRITICAL CONTEXT RULES: "
        "a) X米=bar LENGTH. 三米上面放六米=batang 3m di atas 6m. "
        "b) 把/捆=BUNDLE counters. 包2把=packing 2 bundel. "
        "c) 包(verb)=packing NOT wrapping. "
        "d) 爐號=heat number(NEVER 'nomor panas'). "
        "e) 放=POLYSEMY: 放+把/單/批=RELEASE; 放+地點=PUT/PLACE; 放+料=FEED. "
        "f) 再=POLYSEMY: X再Y(condition)=hanya X yang Y; 再+verb(alone)=lagi/again. "
        "g) 不擋=NOT blocked=ALLOWED. "
        "h) Customer names=keep as-is, do NOT translate. "
        + extra_rule +
        " Only output the translation. No quotes, no explanation, no prefix."
    )

def translate_openai(text, src, tgt, strict=False, repair_mode=False, bad_result=None):
    if not oai:
        return None
    try:
        src_name = LANG_NAMES.get(src, src)
        tgt_name = LANG_NAMES.get(tgt, tgt)
        input_text = text
        cust_placeholders = {}
        if src == "zh":
            input_text, cust_placeholders = pre_replace_zh(text)
        protected, placeholders = protect_mentions(input_text)

        extra_rule = ""
        if strict and src != tgt:
            if src == "zh":
                extra_rule = " IMPORTANT: Do not leave any Chinese words untranslated unless they are a person's name or placeholder."

        sys_prompt = build_system_prompt(extra_rule)

        if repair_mode and bad_result:
            msg = (f"Original text (source language): {protected}\n\n"
                   f"Bad translation that leaked source-language words: {bad_result}\n\n"
                   f"Rewrite the bad translation into pure {tgt_name}. "
                   "Preserve names and __MENTION__ placeholders exactly.")
        else:
            msg = f"Translate from {src_name} to {tgt_name}: {protected}"

        r = oai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": sys_prompt},
                      {"role": "user", "content": msg}],
            temperature=0.1 if strict or repair_mode else 0.2,
            max_tokens=2000,
        )
        result = r.choices[0].message.content.strip()
        result = restore_mentions(result, placeholders)
        if src == "zh":
            result = post_fix_translation(result)
            result = restore_customers(result, cust_placeholders)
        return result
    except Exception as e:
        logger.error("OpenAI error: %s", e)
        return None

def translate_google(text, src, tgt):
    try:
        protected, placeholders = protect_mentions(text)
        lang_map = {"zh": "zh-TW", "id": "id", "en": "en", "vi": "vi",
                    "th": "th", "ja": "ja", "ko": "ko", "ms": "ms", "tl": "tl"}
        sl = lang_map.get(src, src)
        tl = lang_map.get(tgt, tgt)
        q = urllib.parse.quote(protected)
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={sl}&tl={tl}&dt=t&q={q}"
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Mozilla/5.0")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            parts = [item[0] for item in data[0] if item[0]]
            result = "".join(parts)
            result = restore_mentions(result, placeholders)
            result = post_fix_translation(result)
            return result
    except Exception as e:
        logger.error("Google translate error: %s", e)
        return None

def cache_get(text, src, tgt):
    key = (text.strip(), src, tgt)
    if key in translation_cache:
        result, ts = translation_cache[key]
        if time.time() - ts < CACHE_TTL:
            return result
        del translation_cache[key]
    return None

def cache_set(text, src, tgt, result):
    if len(translation_cache) >= CACHE_MAX_SIZE:
        oldest = min(translation_cache, key=lambda k: translation_cache[k][1])
        del translation_cache[oldest]
    translation_cache[(text.strip(), src, tgt)] = (result, time.time())

def translate(text, src, tgt):
    cached = cache_get(text, src, tgt)
    if cached:
        return cached

    result = translate_openai(text, src, tgt)

    # Retry with strict mode if source leakage detected
    if result and not is_translation_valid(result, src, tgt):
        logger.warning("Source leakage detected, retrying strict")
        strict_result = translate_openai(text, src, tgt, strict=True)
        if strict_result and is_translation_valid(strict_result, src, tgt):
            result = strict_result
        else:
            repaired = translate_openai(text, src, tgt, strict=True,
                                        repair_mode=True, bad_result=(strict_result or result))
            if repaired and is_translation_valid(repaired, src, tgt):
                result = repaired

    if result and is_translation_valid(result, src, tgt):
        cache_set(text, src, tgt, result)
        return result

    # Fallback: Google Translate
    result = translate_google(text, src, tgt)
    if result and is_translation_valid(result, src, tgt):
        cache_set(text, src, tgt, result)
        return result

    return None


# ─── Storage query ──────────────────────────────────────
def format_length_zh(code):
    if code == "<=3200": return "未滿3200"
    elif code == ">4200": return "超過4200"
    elif code == ">3200<=4200": return "3200～4200"
    elif code == ">4000": return "超過4000"
    else:
        return code.replace("<=", "未滿").replace(">=", "超過").replace(">", "超過").replace("<", "未滿")

def query_storage(customer_name):
    """Look up storage zone for a customer. Returns embed-ready data or None."""
    entries = STORAGE_LOOKUP.get(customer_name)
    if not entries:
        for key in STORAGE_LOOKUP:
            if key.lower() == customer_name.lower() or customer_name in key or key in customer_name:
                entries = STORAGE_LOOKUP[key]
                customer_name = key
                break
    if not entries:
        return None, None
    return customer_name, entries


# ─── Discord Bot ────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    logger.info(f"Bot online: {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} slash commands")
    except Exception as e:
        logger.error(f"Sync error: {e}")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name="翻譯中... | /help"
    ))


# ─── Auto-translate on message ──────────────────────────
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    # Process commands first
    await bot.process_commands(message)

    ch_id = message.channel.id
    # Check if translation is enabled (default: True)
    if not channel_settings.get(ch_id, True):
        return
    # Check skip list
    if message.author.id in channel_skip_users.get(ch_id, set()):
        return

    text = message.content.strip()
    if not text or text.startswith("/") or text.startswith("!"):
        return
    # Skip very short messages
    if len(text) < 2:
        return

    src = detect_language(text)
    if not src:
        return

    tgt_lang = channel_target_lang.get(ch_id, "id")

    # Determine translation direction
    if src == "zh":
        tgt = tgt_lang
    elif src == tgt_lang:
        tgt = "zh"
    else:
        tgt = "zh"

    if src == tgt:
        return

    result = translate(text, src, tgt)
    if not result:
        return

    flag = LANG_FLAGS.get(tgt, "🌐")

    # Build embed for clean presentation
    embed = discord.Embed(
        description=f"{flag} {result}",
        color=0x06C755  # Green accent
    )
    embed.set_footer(text=f"翻譯 {LANG_NAMES.get(src, src)[:2]} → {LANG_NAMES.get(tgt, tgt)[:2]}")

    try:
        await message.reply(embed=embed, mention_author=False)
    except Exception as e:
        logger.error(f"Reply error: {e}")


# ─── Slash Commands ─────────────────────────────────────

@bot.tree.command(name="help", description="顯示機器人指令說明")
async def cmd_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 翻譯小助手",
        description="華新麗華鹽水廠 — 多語翻譯機器人",
        color=0x06C755
    )
    embed.add_field(name="💬 自動翻譯", value="在頻道中直接輸入文字，自動偵測語言翻譯", inline=False)
    embed.add_field(name="📦 /qry <客戶名>", value="查詢客戶儲區位置", inline=False)
    embed.add_field(name="📢 /notice <訊息>", value="發送雙語公告（中文↔目標語）", inline=False)
    embed.add_field(name="🌐 /lang <語言代碼>", value="設定頻道目標語言（id/en/vi/th/ja/ko/ms/tl）", inline=False)
    embed.add_field(name="🔇 /skip <@使用者>", value="切換某使用者的翻譯跳過狀態", inline=False)
    embed.add_field(name="⏸️ /toggle", value="開關本頻道的自動翻譯", inline=False)
    embed.add_field(name="ℹ️ /status", value="查看本頻道翻譯設定", inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="qry", description="查詢客戶儲區位置")
@app_commands.describe(customer="客戶名稱")
async def cmd_qry(interaction: discord.Interaction, customer: str):
    name, entries = query_storage(customer)
    if not entries:
        await interaction.response.send_message(
            f"❌ 找不到客戶「{customer}」\n💡 試試部分名稱，例如 `DACAPO`、`大成`",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title=f"📦 {name} — 儲區查詢",
        color=0x06C755
    )
    for length, area in entries:
        zh = format_length_zh(length)
        embed.add_field(name=zh, value=f"**{area}**", inline=True)
    embed.set_footer(text="儲區資料 | 華新麗華鹽水廠")
    await interaction.response.send_message(embed=embed)


@cmd_qry.autocomplete("customer")
async def qry_autocomplete(interaction: discord.Interaction, current: str):
    """Autocomplete customer names for /qry"""
    if not current:
        # Show first 25 customers
        choices = [app_commands.Choice(name=k, value=k)
                   for k in sorted(STORAGE_LOOKUP.keys())[:25]]
    else:
        matches = [k for k in STORAGE_LOOKUP.keys()
                   if current.lower() in k.lower()]
        choices = [app_commands.Choice(name=m, value=m) for m in sorted(matches)[:25]]
    return choices


@bot.tree.command(name="notice", description="發送雙語公告")
@app_commands.describe(message="公告內容（中文或印尼文）")
async def cmd_notice(interaction: discord.Interaction, message: str):
    await interaction.response.defer()

    src = detect_language(message)
    if not src:
        src = "zh"

    ch_id = interaction.channel_id
    tgt_lang = channel_target_lang.get(ch_id, "id")
    tgt = tgt_lang if src == "zh" else "zh"

    result = translate(message, src, tgt)
    if not result:
        await interaction.followup.send("❌ 翻譯失敗，請稍後再試")
        return

    src_flag = LANG_FLAGS.get(src, "")
    tgt_flag = LANG_FLAGS.get(tgt, "")

    embed = discord.Embed(
        title="📢 公告 / Pengumuman",
        color=0xFFD700
    )
    embed.add_field(name=f"{src_flag} 原文", value=message, inline=False)
    embed.add_field(name=f"{tgt_flag} 翻譯", value=result, inline=False)
    embed.set_footer(text=f"由 {interaction.user.display_name} 發送")

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="lang", description="設定頻道目標語言")
@app_commands.describe(language="目標語言代碼")
@app_commands.choices(language=[
    app_commands.Choice(name="🇮🇩 印尼文", value="id"),
    app_commands.Choice(name="🇬🇧 英文", value="en"),
    app_commands.Choice(name="🇻🇳 越南文", value="vi"),
    app_commands.Choice(name="🇹🇭 泰文", value="th"),
    app_commands.Choice(name="🇯🇵 日文", value="ja"),
    app_commands.Choice(name="🇰🇷 韓文", value="ko"),
    app_commands.Choice(name="🇲🇾 馬來文", value="ms"),
    app_commands.Choice(name="🇵🇭 菲律賓文", value="tl"),
])
async def cmd_lang(interaction: discord.Interaction, language: app_commands.Choice[str]):
    channel_target_lang[interaction.channel_id] = language.value
    zh_name = LANG_NAMES_ZH.get(language.value, language.value)
    await interaction.response.send_message(
        f"✅ 本頻道目標語言已設為 **{language.name}**（{zh_name}）"
    )


@bot.tree.command(name="skip", description="切換使用者翻譯跳過狀態")
@app_commands.describe(user="要跳過翻譯的使用者")
async def cmd_skip(interaction: discord.Interaction, user: discord.Member):
    ch_id = interaction.channel_id
    if ch_id not in channel_skip_users:
        channel_skip_users[ch_id] = set()

    if user.id in channel_skip_users[ch_id]:
        channel_skip_users[ch_id].discard(user.id)
        await interaction.response.send_message(
            f"✅ **{user.display_name}** 的訊息將恢復翻譯"
        )
    else:
        channel_skip_users[ch_id].add(user.id)
        await interaction.response.send_message(
            f"🔇 **{user.display_name}** 的訊息將不再翻譯"
        )


@bot.tree.command(name="toggle", description="開關本頻道的自動翻譯")
async def cmd_toggle(interaction: discord.Interaction):
    ch_id = interaction.channel_id
    current = channel_settings.get(ch_id, True)
    channel_settings[ch_id] = not current
    status = "開啟 ✅" if not current else "關閉 ❌"
    await interaction.response.send_message(f"翻譯已{status}")


@bot.tree.command(name="status", description="查看本頻道翻譯設定")
async def cmd_status(interaction: discord.Interaction):
    ch_id = interaction.channel_id
    on = channel_settings.get(ch_id, True)
    lang = channel_target_lang.get(ch_id, "id")
    zh_name = LANG_NAMES_ZH.get(lang, lang)
    skip_count = len(channel_skip_users.get(ch_id, set()))
    cache_count = len(translation_cache)
    customer_count = len(STORAGE_LOOKUP)

    embed = discord.Embed(title="📊 頻道翻譯設定", color=0x06C755)
    embed.add_field(name="翻譯狀態", value="✅ 開啟" if on else "❌ 關閉", inline=True)
    embed.add_field(name="目標語言", value=f"{LANG_FLAGS.get(lang, '')} {zh_name}", inline=True)
    embed.add_field(name="跳過人數", value=str(skip_count), inline=True)
    embed.add_field(name="快取數量", value=str(cache_count), inline=True)
    embed.add_field(name="儲區客戶", value=str(customer_count), inline=True)
    embed.add_field(name="GPT 模型", value="gpt-4o-mini", inline=True)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="term", description="查詢工廠術語翻譯")
@app_commands.describe(keyword="中文或印尼文關鍵字")
async def cmd_term(interaction: discord.Interaction, keyword: str):
    results = []
    kw = keyword.strip().lower()
    # Search in ZH_TO_ID_HARD
    for zh, id_text in ZH_TO_ID_HARD.items():
        if kw in zh.lower() or kw in id_text.lower():
            results.append(f"**{zh}** → {id_text}")
    if not results:
        await interaction.response.send_message(
            f"❌ 找不到「{keyword}」相關術語\n💡 試試其他關鍵字",
            ephemeral=True
        )
        return
    # Limit to 20 results
    display = results[:20]
    if len(results) > 20:
        display.append(f"... 還有 {len(results) - 20} 筆")

    embed = discord.Embed(
        title=f"📖 術語查詢：{keyword}",
        description="\n".join(display),
        color=0x06C755
    )
    await interaction.response.send_message(embed=embed)


# ─── Health endpoint (keeps Render free tier alive) ─────
async def health_handler(request):
    return web.Response(text='{"status":"ok"}', content_type="application/json")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/health", health_handler)
    app.router.add_get("/", health_handler)
    port = int(os.environ.get("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Web server started on port {port}")

# ─── Run ────────────────────────────────────────────────
async def main():
    if not DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN not set!")
        exit(1)
    await start_web_server()
    async with bot:
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
