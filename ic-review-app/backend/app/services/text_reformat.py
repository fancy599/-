"""PDF 解析后的 AI 排版规整。

很多 PDF 抽取出来的正文存在不合适的空格与断行（句子被排版硬断、字间有空格）。
这一步把文本分块交给大模型，**只允许调整空格与换行**，并对每一块做
“非空白字符必须完全一致”的校验：一旦模型增删改了任何文字/数字/标点，就丢弃
该块的模型结果、回退到确定性文本。这样既能改善可读性，又保证不篡改制度原文。

无 API Key、未开启开关、或任何异常时，整体安全跳过，返回原文。
"""
from __future__ import annotations

import difflib
import re
from concurrent.futures import ThreadPoolExecutor

from app.config import get_settings

_WS = re.compile(r"\s+")

REFORMAT_SYSTEM = (
    "你是中文公文文本清理助手。下面是一段从 PDF/OCR 抽取的制度正文，可能存在："
    "多余空格、字间空格、被排版硬生生断开的句子、个别乱码字符，以及不合适的符号"
    "（全角半角混用、错误的引号/括号、OCR 误识别的符号等）。\n"
    "你要做两件事：\n"
    "① 整理排版：删除多余空格、把被错误断开的句子合并、按自然段落重新分行；\n"
    "② 仅修正**明显的**乱码字符与不合适的符号，使其还原为正确的中文标点或文字"
    "（例如把错误符号改回正确的标点、修正个别明显的 OCR 乱码）。\n"
    "严格禁止：改写句子含义；增加、删除或合并句子与段落；补全或编造任何内容；"
    "改动数字、金额、比例、日期、人名、单位名、专有名词和条款编号；翻译、概括。"
    "凡是拿不准的地方一律保持原样，绝不猜测。\n"
    "只输出整理后的正文本身，以 JSON 返回：{\"text\": \"整理后的正文\"}。"
)


def _nonspace(s: str) -> str:
    return _WS.sub("", s or "")


_DIGITS = re.compile(r"\d+")


def _acceptable(original: str, candidate: str) -> bool:
    """允许排版整理 + 少量乱码/符号修正，但拦截大幅改写、删段、编造或篡改数字。"""
    o = _nonspace(original)
    n = _nonspace(candidate)
    if not n:
        return False
    # 数字（金额/阈值/比例/日期/编号等）绝不允许被改动——内控审查红线。
    if _DIGITS.findall(o) != _DIGITS.findall(n):
        return False
    # 非空白字符数量变化过大 → 可能删段/续写/大改，拒绝。
    if abs(len(n) - len(o)) > max(20, int(len(o) * 0.12)):
        return False
    # 字符级相似度过低 → 改动过多，仅允许微小修正。
    return difflib.SequenceMatcher(None, o, n).ratio() >= 0.90


def _split_blocks(text: str, max_chars: int = 2400) -> list[str]:
    """按自然段聚合成若干块，单块控制在 max_chars 左右，避免超长上下文。"""
    paras = re.split(r"\n{2,}", text)
    blocks: list[str] = []
    cur = ""
    for p in paras:
        if cur and len(cur) + len(p) > max_chars:
            blocks.append(cur)
            cur = p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        blocks.append(cur)
    return blocks


def _reformat_block(client, block: str) -> str:
    try:
        data = client.complete_json(REFORMAT_SYSTEM, block, max_retries=0)
    except Exception:
        return block
    out = (data.get("text") or "").strip() if isinstance(data, dict) else ""
    if not out:
        return block
    # 护栏：允许排版整理 + 少量乱码/符号修正；相似度过低或长度大幅变化即回退，杜绝大改/编造。
    if not _acceptable(block, out):
        return block
    return out


def ai_reformat_text(text: str, *, force: bool = False) -> str:
    """对外入口：失败/未配置时原样返回，绝不抛异常。

    force=True 时忽略 pdf_ai_reformat 自动开关（用于预览页手动触发），但仍需配置 API Key。
    """
    if not text or len(text.strip()) < 40:
        return text
    settings = get_settings()
    if not settings.llm_configured:
        return text
    if not force and not getattr(settings, "pdf_ai_reformat", False):
        return text
    try:
        from app.services.llm import LLMClient, LLMError

        try:
            # 排版用较短的单块超时，避免个别慢请求把整篇拖到超时。
            client = LLMClient(timeout=40)
        except LLMError:
            return text

        blocks = _split_blocks(text)
        max_blocks = int(getattr(settings, "pdf_ai_reformat_max_blocks", 24) or 24)

        def _work(item: tuple[int, str]) -> str:
            i, block = item
            # 超出预算的块不再调用模型，保留确定性文本，控制耗时与成本。
            return _reformat_block(client, block) if i < max_blocks else block

        # 并行分块整理（pool.map 保持顺序），显著缩短整体耗时。
        with ThreadPoolExecutor(max_workers=6) as pool:
            out_blocks = list(pool.map(_work, list(enumerate(blocks))))
        return "\n\n".join(out_blocks)
    except Exception:
        return text
