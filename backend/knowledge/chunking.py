from dataclasses import dataclass


class ChunkingError(Exception):
    """文本无法按当前配置安全分块。"""


class EmptyDocumentError(ChunkingError):
    """文档规范化后没有文本内容。"""


class ChunkLimitError(ChunkingError):
    """文档分块数量超过配置上限。"""


@dataclass(frozen=True)
class TextChunk:
    content: str
    start: int
    end: int

    @property
    def source_meta(self):
        return {"char_start": self.start, "char_end": self.end}


def split_text(text, chunk_size=800, overlap=100, max_chunks=5000):
    if chunk_size < 1:
        raise ChunkingError("分块大小必须大于零。")
    if overlap < 0 or overlap >= chunk_size:
        raise ChunkingError("分块重叠字符数必须大于等于零且小于分块大小。")
    if max_chunks < 1:
        raise ChunkingError("文档分块上限必须大于零。")

    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    chunks = []
    start = 0
    text_length = len(normalized)
    while start < text_length:
        window_end = min(start + chunk_size, text_length)
        end = _natural_end(normalized, start, window_end, chunk_size)
        raw_content = normalized[start:end]
        leading_whitespace = len(raw_content) - len(raw_content.lstrip())
        trailing_whitespace = len(raw_content) - len(raw_content.rstrip())
        content_start = start + leading_whitespace
        content_end = end - trailing_whitespace
        if content_start < content_end:
            if len(chunks) >= max_chunks:
                raise ChunkLimitError("文档分块数量超过当前上限。")
            chunks.append(
                TextChunk(
                    content=normalized[content_start:content_end],
                    start=content_start,
                    end=content_end,
                )
            )

        if end >= text_length:
            break
        next_start = max(start + 1, end - overlap)
        start = end if next_start >= end else next_start

    return chunks


def _natural_end(text, start, window_end, chunk_size):
    if window_end >= len(text):
        return window_end

    boundary_start = start + chunk_size // 2
    paragraph = text.rfind("\n\n", boundary_start, window_end)
    newline = text.rfind("\n", boundary_start, window_end)
    if paragraph >= boundary_start and paragraph >= newline:
        return paragraph + 2
    if newline >= boundary_start:
        return newline + 1

    punctuation_end = -1
    for punctuation in "。！？；.!?;":
        position = text.rfind(punctuation, boundary_start, window_end)
        if position >= boundary_start:
            punctuation_end = max(punctuation_end, position + 1)
    return punctuation_end if punctuation_end >= boundary_start else window_end
