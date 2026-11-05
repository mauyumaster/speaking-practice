#!/usr/bin/env python3
"""一次练习的状态。跨轮对话里模型会忘，落到盘上就不会。

用法：
    python practice_state.py init --scene A
    python practice_state.py hint --level L1 --node E --text "摄影社 · 联系场地 · 二十多人"
    python practice_state.py hint --level L2 --node E --text "你当时先找的谁？"
    python practice_state.py hint --level L1 --node P_CLOSE --reset --text "回到开头 · 共用的代价"
    python practice_state.py hint --level L1 --node E --back --text "先给个词就行"
    python practice_state.py show
    python practice_state.py done

三条硬拦截（退出码）：
    3  模型自己想降档（用户要求的降档加 --back）
    4  同一段里换节点（换格子了加 --reset，档位会回到 1/3）
    5  3/3 之后还要提示（改说「这段先跳过」）

状态存在 ~/.speaking-practice/session.json（可用 SPEAKING_PRACTICE_DIR 改）。
只依赖标准库。
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

FRAMEWORKS = {"A": "PREP", "B": "STAR", "C": "SCQA"}
SCENES = {"A": "观点表达", "B": "讲述经历", "C": "汇报方案"}
LEVELS = ["L1", "L2", "L3"]


def store_path() -> Path:
    root = os.environ.get("SPEAKING_PRACTICE_DIR")
    base = Path(root) if root else Path.home() / ".speaking-practice"
    base.mkdir(parents=True, exist_ok=True)
    return base / "session.json"


def load() -> dict:
    p = store_path()
    if not p.exists():
        return {"episode": None, "history": []}
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def save(state: dict) -> None:
    with store_path().open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def cmd_init(args) -> int:
    scene = args.scene.upper()
    if scene not in SCENES:
        print(f"场景只能是 A / B / C，收到 {args.scene}", file=sys.stderr)
        return 2
    state = {
        "episode": {
            "id": datetime.now().strftime("%Y%m%d-%H%M%S"),
            "scene": scene,
            "scene_name": SCENES[scene],
            "framework": FRAMEWORKS[scene],
            "started": datetime.now().isoformat(timespec="seconds"),
        },
        "level": None,
        "node": "UNKNOWN",
        "given": [],
        "segments": 1,
        "history": [],
    }
    save(state)
    print(f"已开始：{SCENES[scene]} · {FRAMEWORKS[scene]}  （episode {state['episode']['id']}）")
    return 0


def cmd_hint(args) -> int:
    state = load()
    if not state.get("episode"):
        print("还没有开始练习，先跑 init", file=sys.stderr)
        return 2

    level = args.level.upper()
    if level not in LEVELS:
        print(f"档位只能是 L1 / L2 / L3，收到 {args.level}", file=sys.stderr)
        return 2

    cur = state.get("level")
    node = state.get("node", "UNKNOWN")

    # 换格子：新的一段，档位从第一档重来
    if args.reset:
        node = args.node or node
        cur = None
        state["segments"] = state.get("segments", 1) + 1
        print(f"换到新的一段（节点 {node}），档位从 1/3 重来", file=sys.stderr)

    # 节点：同一段里不许换，换了会让用户觉得被带偏
    if not args.reset and node != "UNKNOWN" and args.node and args.node != node:
        if not args.force:
            print(
                f"拒绝：当前节点是 {node}，不能改成 {args.node}。\n"
                f"      升级换节点会让用户觉得被带偏，前面那档也白给了。\n"
                f"      是从一个格子换到另一个格子了？那就加 --reset（档位会回到 1/3）。",
                file=sys.stderr,
            )
            return 4
        node = args.node
    elif args.node and not args.reset:
        node = args.node

    # 降档只允许用户要求，模型自己不许
    if cur and LEVELS.index(level) < LEVELS.index(cur) and not args.back:
        print(
            f"不允许回退：当前 {cur}，不能给 {level}。\n"
            f"      用户嫌给多了确实要降，加 --back。别自己降。",
            file=sys.stderr,
        )
        return 3

    if cur == level:
        if level == "L3":
            print(
                "拒绝：3/3 已经给过，还卡着就不要再给了。\n"
                "      改说一句「这段先跳过，把后面的说完」，别硬灌。",
                file=sys.stderr,
            )
            return 5
        print(f"注意：{level} 已经给过了，再给同一档通常没有意义（要么升级，要么直接跳过）", file=sys.stderr)

    state["level"] = level
    state["node"] = node
    if args.reset:
        state["given"] = [level]          # 新的一段，重新计数
    else:
        state["given"].append(level)
    state["history"].append(
        {"level": level, "node": node, "text": args.text or "", "at": datetime.now().isoformat(timespec="seconds")}
    )
    save(state)
    mark = LEVELS.index(level) + 1
    print(f"已记录：提示 {mark}/3 · 节点={node} · 本段已给 {'/'.join(state['given'])}")
    return 0


def cmd_node(args) -> int:
    state = load()
    if not state.get("episode"):
        print("还没有开始练习，先跑 init", file=sys.stderr)
        return 2
    state["node"] = args.node.upper()
    save(state)
    print(f"目标节点 = {state['node']}")
    return 0


def cmd_show(args) -> int:
    state = load()
    ep = state.get("episode")
    if not ep:
        print("（还没有开始练习）")
        return 0
    given = "/".join(state.get("given") or []) or "还没给过"
    lv = state.get("level")
    mark = f"提示 {LEVELS.index(lv) + 1}/3（{lv}）" if lv else "未介入"
    print(f"场景　　{ep['scene_name']} · {ep['framework']}")
    print(f"当前档位　{mark}")
    print(f"目标节点　{state.get('node') or 'UNKNOWN'}")
    print(f"本段已给　{given}")
    if state.get("segments", 1) > 1:
        print(f"已换格子　{state['segments']} 段")
    if state.get("history"):
        last = state["history"][-1]
        print(f"上一句　　{last['text']}")
    return 0


def cmd_done(args) -> int:
    state = load()
    ep = state.get("episode")
    if not ep:
        print("（没有进行中的练习）")
        return 0
    print(f"结束：{ep['scene_name']}，共给过 {'/'.join(state.get('given') or []) or '0'} 档提示")
    state["episode"] = None
    state["level"] = None
    state["node"] = "UNKNOWN"
    state["given"] = []
    save(state)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="表达陪练的状态")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="开始一次练习")
    p.add_argument("--scene", required=True, help="A 观点 / B 经历 / C 汇报")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("hint", help="记录一档提示")
    p.add_argument("--level", required=True, help="L1 / L2 / L3")
    p.add_argument("--node", help="目标节点，如 P_OPEN / R / E / P_CLOSE")
    p.add_argument("--text", help="上屏的那句话")
    p.add_argument("--force", action="store_true", help="确认判断错了节点，同一段内允许改节点")
    p.add_argument("--reset", action="store_true", help="换到另一个格子：节点可改，档位回到 1/3")
    p.add_argument("--back", action="store_true", help="用户嫌给多了要降档（模型自己不许降）")
    p.set_defaults(func=cmd_hint)

    p = sub.add_parser("node", help="改目标节点")
    p.add_argument("node")
    p.set_defaults(func=cmd_node)

    p = sub.add_parser("show", help="看当前状态")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("done", help="结束这次练习")
    p.set_defaults(func=cmd_done)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
