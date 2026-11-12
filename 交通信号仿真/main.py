"""项目入口：调用 apps/ 下的应用。

    python main.py                   启动 Pygame 桌面仿真（默认 3×3 网格）
    python main.py --speed 10        10 倍速启动（运行中按 + / - 调速）
    python main.py --grid 2x2        指定网格尺寸（1x1 为单路口）
    python main.py --no-coordinated  关闭绿波协调（各路口独立配时）
    python main.py --web             启动 Web 控制面板
    python main.py --batch           单路口批量对比实验
    python main.py --network         多路口网格绿波协调实验（支持 --jobs 并行）
    python main.py --html            生成单文件 HTML 报告
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--batch" in argv:
        from apps.batch_experiment import main as batch_main

        argv.remove("--batch")
        return batch_main(argv)
    if "--network" in argv:
        from apps.batch_network import main as network_main

        argv.remove("--network")
        return network_main(argv)
    if "--html" in argv:
        from apps.html_report import main as html_main

        argv.remove("--html")
        return html_main(argv)
    if "--web" in argv:
        from apps.web_app import main as web_main

        argv.remove("--web")
        return web_main(argv)
    from apps.desktop import main as desktop_main

    return desktop_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
