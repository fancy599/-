"""命令行测试百度智能云·文档解析。

用法（在 backend 目录、已装依赖、已配置 .env 的环境下）：
    python test_baidu_parse.py 某份制度.pdf

会调用 AK/SK → 提交 PDF → 轮询 → 打印解析文本的前 2000 字与总字数。
"""
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python test_baidu_parse.py <pdf路径>")
        return 2
    pdf = sys.argv[1]
    if not Path(pdf).exists():
        print(f"文件不存在: {pdf}")
        return 2

    from app.config import get_settings
    from app.services.baidu_doc_parser import parse_pdf, BaiduDocParserError

    s = get_settings()
    print(f"提供方: {s.pdf_parser_provider} | 百度已配置: {s.baidu_doc_parser_configured}")
    if not s.baidu_doc_parser_configured:
        print("未配置 BAIDU_OCR_API_KEY / BAIDU_OCR_SECRET_KEY，请检查 .env")
        return 1
    try:
        print("正在调用百度·文档解析（提交+轮询，可能需要数十秒）...")
        text = parse_pdf(pdf)
    except BaiduDocParserError as e:
        print(f"解析失败: {e}")
        return 1
    print(f"\n=== 解析成功，共 {len(text)} 字 ===\n")
    print(text[:2000])
    print("\n...（仅显示前 2000 字）" if len(text) > 2000 else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
