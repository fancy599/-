from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    # 部分推理模型（如 o1/o3 或部分国产模型）仅允许 temperature=1；留空则自动探测
    llm_temperature: float | None = None
    llm_timeout_seconds: float = 60.0
    llm_fallback_model: str = ""
    llm_retry_backoff_seconds: float = 0.5
    max_agent_turns: int = 3
    gpu_queue_enabled: bool = False
    task_executor: str = "local_thread"
    redis_url: str = "redis://127.0.0.1:6379/0"
    core_analyser_model: str = ""
    soe_expert_model: str = ""
    core_analyser_api_key: str = ""
    core_analyser_base_url: str = ""
    core_analyser_fallback_model: str = ""
    soe_expert_api_key: str = ""
    soe_expert_base_url: str = ""
    soe_expert_fallback_model: str = ""
    hybrid_map_workers: int = 3

    @property
    def resolved_core_model(self) -> str:
        return self.core_analyser_model.strip() or self.llm_model

    @property
    def resolved_expert_model(self) -> str:
        return self.soe_expert_model.strip() or self.llm_model

    @property
    def dual_model_configured(self) -> bool:
        return bool(self.core_analyser_model.strip() and self.soe_expert_model.strip())

    database_url: str = f"sqlite:///{ROOT_DIR / 'data' / 'ic_review.db'}"
    upload_dir: str = str(ROOT_DIR / "data" / "uploads")
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    auto_seed: bool = False

    max_pdf_pages: int = 300
    # fast=本地拆条+1次LLM审差异（约1-3分钟）；full=六步全LLM（约8-20分钟）
    pipeline_mode: str = "hybrid"
    # PDF 解析后是否用大模型仅整理空格/换行（不改文字，校验不通过自动回退）；无 API Key 时自动跳过
    pdf_ai_reformat: bool = True
    pdf_ai_reformat_max_blocks: int = 24

    # 集团对照·专家仲裁的门控阈值：置信度低于该值（或高风险/关键差异）才升级给强模型仲裁，
    # 其余采纳 Core Analyser 初判。建议后续用评测集调优。
    expert_review_confidence_threshold: float = 0.8

    # 联网搜索（用于"通用内控设计体检"兜底时补充外部监管要求依据）。
    # 默认 Tavily 兼容接口；留空 web_search_api_key 则不启用，兜底审查仍以大模型自身知识进行。
    web_search_provider: str = "tavily"
    web_search_api_key: str = ""
    web_search_base_url: str = "https://api.tavily.com"
    web_search_max_results: int = 5

    # PDF 解析提供方：baidu=百度智能云·文档解析（需配置 AK/SK，失败自动回退本地）；local=本地 PyMuPDF。
    pdf_parser_provider: str = "baidu"
    baidu_ocr_api_key: str = ""
    baidu_ocr_secret_key: str = ""
    baidu_oauth_url: str = "https://aip.baidubce.com/oauth/2.0/token"
    baidu_doc_parser_submit_url: str = "https://aip.baidubce.com/rest/2.0/brain/online/v2/parser/task"
    baidu_doc_parser_query_url: str = "https://aip.baidubce.com/rest/2.0/brain/online/v2/parser/task/query"
    baidu_doc_parser_timeout_seconds: float = 180.0
    baidu_doc_parser_poll_interval: float = 5.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def llm_configured(self) -> bool:
        global_key_ready = bool(self.llm_api_key and self.llm_api_key != "sk-your-key-here")
        core_key_ready = bool(
            self.core_analyser_api_key and self.core_analyser_api_key != "sk-your-key-here"
        )
        expert_key_ready = bool(
            self.soe_expert_api_key and self.soe_expert_api_key != "sk-your-key-here"
        )
        return global_key_ready or (core_key_ready and expert_key_ready)

    @property
    def baidu_doc_parser_configured(self) -> bool:
        return bool(self.baidu_ocr_api_key.strip() and self.baidu_ocr_secret_key.strip())

    @property
    def web_search_configured(self) -> bool:
        return bool(self.web_search_api_key.strip())

    @property
    def use_baidu_pdf_parser(self) -> bool:
        return self.pdf_parser_provider.strip().lower() == "baidu" and self.baidu_doc_parser_configured


@lru_cache
def get_settings() -> Settings:
    return Settings()
