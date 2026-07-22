"""
BM25 关键词检索与 Reciprocal Rank Fusion (RRF) — 补充向量检索的精确匹配能力

第3层检索的配套模块，为 MemoryRetriever 提供基于 BM25 算法的关键词检索，
以及 RRF 融合策略将向量检索与关键词检索结果合并排序。

Classes:
    BM25Retriever:   BM25 索引构建与检索器
    reciprocal_rank_fusion:  标准 RRF 融合函数（模块级）
"""

from __future__ import annotations

import math
import re
import time
from collections import defaultdict
from typing import Any, Optional

from src.common.logger import get_logger
from src.memory.atom import get_fade_level
from src.memory.layer3_retrieval import RetrievedAtom
from src.memory.schema import MemoryAtom as MemoryAtomModel, memory_db
from src.memory.store import MemoryStore

logger = get_logger("memory.bm25")

# ---------------------------------------------------------------------------
# CJK 字符范围（与 layer1_summarizer 保持一致）
# ---------------------------------------------------------------------------

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")


def _is_cjk(char: str) -> bool:
    """判断单字符是否为 CJK 统一表意文字"""
    return bool(_CJK_RE.match(char))


def tokenize(text: str) -> list[str]:
    """CJK 感知分词器

    对 CJK 字符按 bigram（2-gram）切分，非 CJK 部分按空白符切分。
    统一转为小写以归一化匹配。

    Args:
        text: 输入文本

    Returns:
        词元列表
    """
    tokens: list[str] = []
    i = 0
    length = len(text)
    ascii_buf: list[str] = []

    while i < length:
        ch = text[i]
        if _is_cjk(ch):
            # 刷出 ASCII 缓冲
            if ascii_buf:
                ascii_word = "".join(ascii_buf).lower()
                tokens.extend(ascii_word.split())
                ascii_buf = []
            # 收集连续 CJK 字符
            j = i
            while j < length and _is_cjk(text[j]):
                j += 1
            cjk_str = text[i:j]
            # 生成长度 ≥ 2 时截取 bigram
            if len(cjk_str) >= 2:
                tokens.extend(cjk_str[k : k + 2] for k in range(len(cjk_str) - 1))
            # 单字 CJK 直接作为词元
            elif len(cjk_str) == 1:
                tokens.append(cjk_str)
            i = j
        else:
            ascii_buf.append(ch)
            i += 1

    # 末尾 ASCII 缓冲
    if ascii_buf:
        ascii_word = "".join(ascii_buf).lower()
        tokens.extend(ascii_word.split())

    return tokens


# ---------------------------------------------------------------------------
# RRF 融合函数
# ---------------------------------------------------------------------------


def reciprocal_rank_fusion(
    results_lists: list[list[RetrievedAtom]],
    k: int = 60,
) -> list[RetrievedAtom]:
    """Reciprocal Rank Fusion — 将多个排序列表融合为一个排序

    标准 RRF 公式:
        score(d) = Σₗ 1 / (k + rankₗ(d))

    其中 rankₗ(d) 是文档 d 在第 l 个列表中的排序位置（从 1 开始）。

    Args:
        results_lists: 多个排序检索结果列表
        k: RRF 常数（默认 60，经验值）

    Returns:
        融合后的排序结果，按 RRF 得分降序排列
    """
    return weighted_reciprocal_rank_fusion(results_lists, [1.0] * len(results_lists), k=k)


def weighted_reciprocal_rank_fusion(
    results_lists: list[list[RetrievedAtom]],
    weights: list[float],
    k: int = 60,
) -> list[RetrievedAtom]:
    """Fuse ranked retrieval lists with per-retriever RRF weights."""
    if len(results_lists) != len(weights):
        raise ValueError("results_lists and weights must have the same length")
    if not results_lists:
        return []

    doc_scores: dict[str, float] = {}
    doc_map: dict[str, RetrievedAtom] = {}
    for results, weight in zip(results_lists, weights, strict=True):
        for rank, atom in enumerate(results, 1):
            aid = atom.atom_id
            doc_scores[aid] = doc_scores.get(aid, 0.0) + weight / (k + rank)
            if aid not in doc_map:
                doc_map[aid] = atom

    ranked = sorted(doc_scores, key=lambda aid: doc_scores[aid], reverse=True)
    fused: list[RetrievedAtom] = []
    for aid in ranked:
        atom = doc_map[aid]
        atom.final_score = doc_scores[aid]
        fused.append(atom)
    return fused


# ---------------------------------------------------------------------------
# BM25 检索器
# ---------------------------------------------------------------------------


class BM25Retriever:
    """BM25 关键词检索器

    构建内存倒排索引，支持 BM25 关键词检索及与向量检索结果的 RRF 融合。
    索引按需构建，可通过 invalidate_cache() 强制重建。

    BM25 公式:
        score(D, Q) = Σₜ IDF(t) · (tf(t,D) · (k₁ + 1)) / (tf(t,D) + k₁ · (1 - b + b · |D|/avgdl))

        IDF(t) = log((N - df(t) + 0.5) / (df(t) + 0.5) + 1)

    使用方式:
        retriever = BM25Retriever(store)
        results = await retriever.search("你好世界", top_k=10)
        fused = await retriever.hybrid_search("你好", vector_results)
    """

    def __init__(
        self,
        store: MemoryStore,
        k1: float = 1.5,
        b: float = 0.75,
    ):
        """初始化 BM25 检索器

        Args:
            store: MemoryStore 实例
            k1: BM25 词频饱和参数（1.2–2.0，默认 1.5）
            b: BM25 长度归一化参数（0.0–1.0，默认 0.75）
        """
        self.store = store
        self.k1 = k1
        self.b = b

        # 索引状态
        self._index_built = False
        self._doc_count = 0
        self._avg_doc_length = 0.0

        # 倒排索引: term -> {doc_id: term_frequency}
        self._inverted_index: dict[str, dict[str, int]] = defaultdict(dict)
        # 文档长度: doc_id -> token_count
        self._doc_lengths: dict[str, int] = {}
        # 文档内容缓存
        self._doc_contents: dict[str, str] = {}
        # 文档元数据缓存
        self._doc_metadata: dict[str, dict[str, Any]] = {}
        # 文档类型过滤缓存
        self._doc_source_scene: dict[str, str] = {}
        self._doc_source_id: dict[str, Optional[str]] = {}

    # ── 索引构建 ───────────────────────────────────────────────

    async def _ensure_index(self) -> None:
        """确保索引已构建"""
        if not self._index_built:
            await self._build_bm25_index()

    async def _build_bm25_index(self) -> None:
        """从 SQLite 加载所有活跃记忆原子，构建内存倒排索引"""
        # 清空旧索引
        self._inverted_index.clear()
        self._doc_lengths.clear()
        self._doc_contents.clear()
        self._doc_metadata.clear()
        self._doc_source_scene.clear()
        self._doc_source_id.clear()

        total_tokens = 0

        try:
            with memory_db:
                query = MemoryAtomModel.select().where(MemoryAtomModel.status == "active")

                for model in query:
                    doc_id = model.atom_id
                    content = model.content or ""

                    tokens = tokenize(content)
                    token_count = len(tokens)

                    self._doc_contents[doc_id] = content
                    self._doc_lengths[doc_id] = token_count
                    total_tokens += token_count

                    # 缓存元数据
                    self._doc_metadata[doc_id] = {
                        "atom_id": model.atom_id,
                        "atom_type": model.atom_type,
                        "weight": model.weight,
                        "source_scene": model.source_scene,
                        "source_id": model.source_id,
                        "privacy_level": model.privacy_level,
                        "status": model.status,
                        "importance": model.importance,
                        "confidence": model.confidence,
                        "created_at": model.created_at,
                    }
                    self._doc_source_scene[doc_id] = model.source_scene
                    self._doc_source_id[doc_id] = model.source_id

                    # 统计 term frequency
                    tf: dict[str, int] = {}
                    for token in tokens:
                        tf[token] = tf.get(token, 0) + 1

                    # 写入倒排索引
                    for token, count in tf.items():
                        self._inverted_index[token][doc_id] = count

            self._doc_count = len(self._doc_lengths)
            self._avg_doc_length = total_tokens / self._doc_count if self._doc_count > 0 else 0.0
            self._index_built = True

            logger.info(
                "BM25 索引构建完成",
                extra={
                    "doc_count": self._doc_count,
                    "unique_terms": len(self._inverted_index),
                    "avg_doc_length": round(self._avg_doc_length, 2),
                },
            )

        except Exception as e:
            logger.error(f"BM25 索引构建失败: {e}")
            self._index_built = False

    # ── IDF 计算 ────────────────────────────────────────────────

    def _idf(self, term: str) -> float:
        """计算 term 的 IDF 值

        BM25 的 IDF 变体（平滑版本，避免负值）:
            IDF(t) = log((N - df(t) + 0.5) / (df(t) + 0.5) + 1)
        """
        df = len(self._inverted_index.get(term, {}))
        if df == 0:
            return 0.0
        return math.log((self._doc_count - df + 0.5) / (df + 0.5) + 1.0)

    # ── BM25 评分 ──────────────────────────────────────────────

    def _calculate_bm25_score(self, query_terms: list[str], doc_id: str) -> float:
        """计算单个文档的 BM25 得分

        BM25 公式:
            score = Σₜ IDF(t) · (tf · (k₁ + 1)) / (tf + k₁ · (1 - b + b · dl / avgdl))

        Args:
            query_terms: 查询词元列表
            doc_id: 目标文档 ID

        Returns:
            BM25 得分
        """
        doc_len = self._doc_lengths.get(doc_id, 0)
        if doc_len == 0:
            return 0.0

        score = 0.0
        norm = 1.0 - self.b + self.b * (doc_len / self._avg_doc_length) if self._avg_doc_length > 0 else 1.0

        for term in query_terms:
            postings = self._inverted_index.get(term)
            if postings is None:
                continue

            tf = postings.get(doc_id, 0)
            if tf == 0:
                continue

            idf = self._idf(term)
            score += idf * (tf * (self.k1 + 1.0)) / (tf + self.k1 * norm)

        return score

    # ── 检索方法 ──────────────────────────────────────────────

    @staticmethod
    def _matches_filter(actual: Any, expected: Any) -> bool:
        """Match one cached payload value using Qdrant-compatible list semantics."""
        if isinstance(expected, (list, tuple, set)):
            return actual in expected
        return actual == expected

    def _matches_filters(
        self,
        doc_id: str,
        partition: Optional[str],
        filters: Optional[dict[str, Any]],
    ) -> bool:
        """Apply supported memory payload filters to one indexed document."""
        metadata = self._doc_metadata.get(doc_id, {})
        if partition and metadata.get("source_scene") != partition:
            return False

        supported_fields = {
            "atom_id",
            "atom_type",
            "privacy_level",
            "source_id",
            "source_scene",
            "status",
        }
        for key, expected in (filters or {}).items():
            if key not in supported_fields or expected is None:
                continue
            if not self._matches_filter(metadata.get(key), expected):
                return False
        return True

    async def search(
        self,
        query: str,
        top_k: int = 10,
        partition: Optional[str] = None,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[RetrievedAtom]:
        """BM25 关键词检索

        对查询进行 CJK 分词，计算每个候选文档的 BM25 得分，
        返回得分最高的 top_k 条结果。

        Args:
            query: 查询文本
            top_k: 返回结果数量
            partition: 场景分区过滤（如 "group_chat"，None 表示不过滤）
            filters: 记忆 payload 过滤条件，支持场景、来源、类型、隐私级别和状态

        Returns:
            检索到的记忆原子列表，按 BM25 得分降序
        """
        if not query.strip():
            return []

        await self._ensure_index()
        if self._doc_count == 0:
            return []

        _start = time.monotonic()
        query_terms = tokenize(query)
        if not query_terms:
            return []

        logger.debug(
            "BM25检索开始",
            query_len=len(query),
            index_size=len(self._doc_lengths),
        )

        # 收集所有命中文档
        candidate_docs: set[str] = set()
        for term in query_terms:
            postings = self._inverted_index.get(term)
            if postings:
                candidate_docs.update(postings.keys())

        if not candidate_docs:
            return []

        # 计算 BM25 得分
        doc_scores: dict[str, float] = {}
        for doc_id in candidate_docs:
            if not self._matches_filters(doc_id, partition, filters):
                continue
            doc_scores[doc_id] = self._calculate_bm25_score(query_terms, doc_id)

        if not doc_scores:
            return []

        # 排序并取 top_k
        sorted_docs = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)
        top_docs = sorted_docs[:top_k]

        # 构建结果
        results: list[RetrievedAtom] = []
        for doc_id, bm25_score in top_docs:
            meta = self._doc_metadata.get(doc_id, {})

            atom = RetrievedAtom(
                atom_id=doc_id,
                content=self._doc_contents.get(doc_id, ""),
                atom_type=meta.get("atom_type", ""),
                weight=float(meta.get("weight", 0.0)),
                similarity_score=bm25_score,
                final_score=bm25_score,
                fade_level=get_fade_level(float(meta.get("weight", 0.0))),
                source_scene=meta.get("source_scene", "unknown"),
                source_id=meta.get("source_id"),
                importance=float(meta.get("importance", 0.5)),
                confidence=float(meta.get("confidence", 0.5)),
            )

            created_at = meta.get("created_at")
            if created_at is not None:
                if isinstance(created_at, (int, float)):
                    atom.created_at = created_at
                elif hasattr(created_at, "timestamp"):
                    atom.created_at = created_at.timestamp()

            results.append(atom)

        elapsed = time.monotonic() - _start
        logger.debug(
            "BM25检索完成",
            query_len=len(query),
            results_count=len(results),
            time_ms=round(elapsed * 1000),
        )
        return results

    async def hybrid_search(
        self,
        query: str,
        vector_results: list[RetrievedAtom],
        top_k: int = 10,
        bm25_weight: float = 0.3,
        vector_weight: float = 0.7,
    ) -> list[RetrievedAtom]:
        """混合检索 — BM25 × 向量检索的加权 RRF 融合

        先执行 BM25 关键词检索，再与向量检索结果通过加权 RRF 融合。
        加权 RRF 公式:
            score(d) = w_bm25 · Σ 1/(k + rank_bm25(d))
                     + w_vector · Σ 1/(k + rank_vector(d))

        Args:
            query: 查询文本
            vector_results: 向量检索结果列表（RetrievedAtom 列表）
            top_k: 最终返回结果数量
            bm25_weight: BM25 结果权重（默认 0.3）
            vector_weight: 向量检索结果权重（默认 0.7）

        Returns:
            融合排序后的结果列表
        """
        if not query.strip():
            return vector_results[:top_k]

        # 执行 BM25 检索（取更多候选以提升融合效果）
        bm25_results = await self.search(query, top_k=top_k * 3)

        if not bm25_results:
            return vector_results[:top_k]

        if not vector_results:
            return bm25_results[:top_k]

        results = weighted_reciprocal_rank_fusion(
            [bm25_results, vector_results],
            [bm25_weight, vector_weight],
        )[:top_k]

        logger.debug(
            "混合检索完成(RRF)",
            query=query[:50],
            bm25_results=len(bm25_results),
            vector_results=len(vector_results),
            fused_results=len(results),
        )

        return results

    # ── 缓存管理 ──────────────────────────────────────────────

    def update_cached_metadata(self, atom_id: str, updates: dict[str, Any]) -> None:
        """Refresh non-lexical metadata without rebuilding term statistics."""
        if not self._index_built or atom_id not in self._doc_metadata:
            return

        metadata_fields = {
            "atom_type",
            "confidence",
            "created_at",
            "importance",
            "privacy_level",
            "source_id",
            "source_scene",
            "weight",
        }
        metadata = self._doc_metadata[atom_id]
        for key, value in updates.items():
            if key in metadata_fields:
                metadata[key] = value
        if "source_scene" in updates:
            self._doc_source_scene[atom_id] = str(updates["source_scene"])
        if "source_id" in updates:
            self._doc_source_id[atom_id] = updates["source_id"]

    def invalidate_cache(self) -> None:
        """使索引缓存失效，下次 search 将自动重建"""
        self._index_built = False
        self._doc_count = 0
        self._avg_doc_length = 0.0
        self._inverted_index.clear()
        self._doc_lengths.clear()
        self._doc_contents.clear()
        self._doc_metadata.clear()
        self._doc_source_scene.clear()
        self._doc_source_id.clear()

        logger.debug("BM25 索引缓存已失效")
