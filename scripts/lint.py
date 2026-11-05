#!/usr/bin/env python3
"""越界检查：一条提示是不是给多了，一次评分是不是有据。

用法：
    # 查一条提示
    python lint.py hint --level L2 --text "你当时具体做了什么？" --transcript "..."

    # 查一次评分（dims 是 JSON 数组，见 reference/rubric.md）
    python lint.py score --json dims.json --transcript "..."

    # 也可以从标准输入读
    echo '[...]' | python lint.py score --transcript "..."

退出码：全过 0，有 FAIL 1，参数错 2。只依赖标准库。

判据来自 reference/ladder.md 与 reference/rubric.md —— 改规则时两边一起改。
"""

import argparse
import json
import re
import sys
import unicodedata

# 框架词：只用这些词当 L1，等于没给提示
FRAMEWORK_WORDS = {
    "观点", "理由", "例子", "例证", "总结", "收束", "观点表达",
    "情境", "任务", "行动", "结果", "背景", "冲突", "问题", "答案", "方案",
}

# 评价用户、空泛鼓励、代写的口吻
EVAL_PATTERNS = [
    r"你应该", r"你不应该", r"显然", r"很明显",
    r"表达能力", r"逻辑不", r"语言组织", r"水平",
    r"很棒", r"非常好", r"做得不错", r"有进步", r"继续保持", r"加油",
    r"你可以这样说", r"可以这么说", r"照着念", r"给你一个范例", r"参考这段话",
]

# 留空位：…… / ... / 【…】 / 〔…〕 / […]
PLACEHOLDER = re.compile(r"…{2,}|\.{3,}|【[^】]*】|〔[^〕]*〕|\[[^\]]*\]")

# 档位标记：〔提示 1/3 · 关键词〕
MARKER = re.compile(r"〔\s*提示\s*(\d)\s*/\s*3\s*·\s*(关键词|一个问题|句式)\s*〕")
LEVEL_NAME = {"L1": "关键词", "L2": "一个问题", "L3": "句式"}
NAME_LEVEL = {v: k for k, v in LEVEL_NAME.items()}
LEVELS_INDEX = {"L1": 0, "L2": 1, "L3": 2}

NOISE = " "


def norm(s: str) -> str:
    """去掉全部标点与空白。转写会补标点，严格逐字对不上是常态。"""
    return "".join(
        ch for ch in (s or "")
        if not ch.isspace() and not unicodedata.category(ch).startswith("P")
    )


def report(code: str, ok: bool, fail: str, good: str = "通过") -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {code:<4s} {good if ok else fail}")
    return ok


def split_items(text: str):
    return [x.strip() for x in re.split(r"[·・、，,/／]", text) if x.strip()]


# ---------- 数字与量词 ----------

CN_DIGIT = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
            "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
CN_UNIT = {"十": 10, "百": 100, "千": 1000, "万": 10000}

# 数字 + 可选「多/余/来」+ 量词。用来抓「十二家」被改成「二十家」这种。
QTY = re.compile(r"(\d+|[零一二三四五六七八九十百千万两]+)[多余来]?([家个人次天年月块张条位分秒岁届周])")


def cn2int(s: str):
    """中文数字转整数，只处理表达数量的常见形式；转不了就返回 None。"""
    if s.isdigit():
        return int(s)
    total = section = num = 0
    for ch in s:
        if ch in CN_DIGIT:
            num = CN_DIGIT[ch]
        elif ch in CN_UNIT:
            u = CN_UNIT[ch]
            if u == 10000:
                total = (total + section + num) * 10000
                section = num = 0
            else:
                section += (num or 1) * u
                num = 0
        else:
            return None
    return total + section + num


def quantities(text: str):
    """抽出 (数值, 量词)，只留 ≥10 的 —— 小数字多是「第一次」这类序数，误报率高。"""
    out = set()
    for raw, unit in QTY.findall(text or ""):
        n = cn2int(raw)
        if n is not None and n >= 10:
            out.add((n, unit))
    return out


# ---------- hint ----------

def check_hint(level: str, text: str, transcript: str) -> bool:
    level = level.upper()
    raw = (text or "").strip()
    ok = True
    limit = {"L1": 40, "L2": 60, "L3": 90}.get(level, 60)

    # H0 档位有没有写在脸上，且和在给的那一档对得上
    m = MARKER.search(raw)
    body = raw
    if m:
        shown_n, shown_name = int(m.group(1)), m.group(2)
        shown_level = NAME_LEVEL.get(shown_name, "")
        ok &= report(
            "H0",
            shown_level == level and shown_n == LEVELS_INDEX.get(level, -1) + 1,
            f"标记写的是「{shown_n}/3 · {shown_name}」，实际在给 {level}（{LEVEL_NAME.get(level,'')}）",
            f"标了 {shown_n}/3 · {shown_name}",
        )
        body = raw[: m.start()] + raw[m.end():]
    else:
        ok &= report("H0", False, "没有档位标记「〔提示 n/3 · 档位名〕」，用户不知道现在第几档", "")

    text = body.strip()

    # H1 给的内容其实是别的档
    if level == "L1":
        ok &= report("H1", "？" not in text and "?" not in text, "L1 是问句，那是 L2 的内容", "形状是词串")
        ok &= report("H1b", not PLACEHOLDER.search(text), "L1 带句式空位，那是 L3 的内容", "没有越到 L3")
    elif level == "L2":
        qn = text.count("？") + text.count("?")
        ok &= report("H1", qn == 1, f"L2 只能有一个问号，实际 {qn} 个", "只问了一件事")
        ok &= report("H1b", not PLACEHOLDER.search(text), "L2 带句式空位，那是 L3 的内容", "没有越到 L3")
    else:
        ok &= report("H4", bool(PLACEHOLDER.search(text)), "L3 必须留空位（…… 或 【…】），否则就是代写", "留了空位")

    # H2 代写：去掉占位符后还剩多少实义文本。词串 10 字上下，代写 20 字以上
    rest = norm(PLACEHOLDER.sub("", text))
    cap = 24 if level == "L3" else 18
    ok &= report("H2", len(rest) <= cap, f"去掉空位后还有 {len(rest)} 字，接近可直接照念的整段", f"实义 {len(rest)} 字，念不出来")

    # H3 字数
    if level == "L1":
        items = split_items(text)
        long_items = [x for x in items if len(x) > 10]
        ok &= report("H3", not long_items, f"L1 每项 ≤10 字，超了：{long_items}", "每项都在 10 字内")
        ok &= report("H3b", 2 <= len(items) <= 3, f"L1 应是 2–3 项，实际 {len(items)} 项", f"{len(items)} 项")
    else:
        ok &= report("H3", len(text) <= limit, f"{level} ≤{limit} 字，实际 {len(text)} 字", f"{len(text)} 字，在 {limit} 内")

    # H5 敷衍：L1 全是框架词
    if level == "L1":
        items = split_items(text)
        filler = [x for x in items if x in FRAMEWORK_WORDS]
        ok &= report("H5", len(filler) < len(items) or not items, f"拿框架词当关键词用：{filler}", "落到了具体内容")

    # H6 评价、空泛鼓励、代写口吻
    hits = [p for p in EVAL_PATTERNS if re.search(p, text)]
    ok &= report("H6", not hits, f"出现评价、空泛鼓励或代写口吻：{hits}", "没有评价用户")

    # H7 编造：提示里的「数字＋量词」在原话里找不到同样的组合
    if transcript:
        invented = sorted(quantities(text) - quantities(transcript))
        shown = [f"{n}{u}" for n, u in invented]
        ok &= report("H7", not invented, f"提示里的数量在原话里找不到：{shown}", "数量都有出处")

    return ok


# ---------- score ----------

def check_score(payload, transcript: str) -> bool:
    ok = True

    # 两种写法都收：{"dims":[...], "total":x} 或裸数组
    if isinstance(payload, dict):
        dims = payload.get("dims")
        declared = payload.get("total")
    elif isinstance(payload, list):
        dims = payload
        declared = None
    else:
        return report("S1", False, "应为 {dims, total} 或数组", "")

    if not isinstance(dims, list):
        return report("S1", False, "dims 应是数组", "")

    ok &= report("S1", len(dims) == 4, f"应为 4 维，实际 {len(dims)} 维", "四维齐全")

    total = 0.0
    bad_range, bad_quote, bad_decimal, missing_quote = [], [], [], []

    for d in dims:
        if not isinstance(d, dict):
            continue
        label = d.get("label") or d.get("id") or "?"
        try:
            sc = float(d.get("score"))
        except (TypeError, ValueError):
            bad_range.append(f"{label}=非数字")
            continue

        if not 0 <= sc <= 4:
            bad_range.append(f"{label}={sc}")
        if round(sc, 1) != sc:
            bad_decimal.append(f"{label}={sc}")
        total += sc

        quote = (d.get("quote") or "").strip()
        if sc > 0 and not quote:
            missing_quote.append(label)
        elif quote and transcript and norm(quote) not in norm(transcript):
            bad_quote.append(f"{label}「{quote}」")

    ok &= report("S2", not bad_range, f"分数越界或非数字：{bad_range}", "分数都在 0–4")
    ok &= report("S2b", not bad_decimal, f"应保留一位小数：{bad_decimal}", "都是一位小数")
    ok &= report("S3", not missing_quote, f"有分但没给引用：{missing_quote}", "有分的都附了引用")
    ok &= report("S4", not bad_quote, f"引用在原话里搜不到：{bad_quote}", "引用都能逐字对上")

    if declared is not None:
        ok &= report(
            "S5",
            abs(float(declared) - round(total, 1)) < 1e-6,
            f"总分 {declared} 与四维相加 {round(total, 1)} 不符",
            "总分与四维相符",
        )

    print(f"\n（四维相加 {round(total, 1)} / 16.0）")
    return ok


def load_dims(path):
    if path:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return json.load(sys.stdin)


def main() -> int:
    ap = argparse.ArgumentParser(description="检查提示是否越界、评分是否有据")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("hint", help="检查一条提示")
    p.add_argument("--level", required=True, help="L1 / L2 / L3")
    p.add_argument("--text", required=True, help="上屏的那句话")
    p.add_argument("--transcript", default="", help="用户原话，用于查编造")
    p.set_defaults(func=lambda a: check_hint(a.level, a.text, a.transcript))

    p = sub.add_parser("score", help="检查一次评分")
    p.add_argument("--json", help="dims.json 路径；不给则读标准输入")
    p.add_argument("--transcript", required=True, help="用户原话，用于核对引用")
    p.set_defaults(func=lambda a: check_score(load_dims(a.json), a.transcript))

    args = ap.parse_args()
    try:
        ok = args.func(args)
    except FileNotFoundError:
        print("找不到 JSON 文件", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"JSON 解析失败：{e}", file=sys.stderr)
        return 2

    print("\n全过。" if ok else "\n有 FAIL，改完再来。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
