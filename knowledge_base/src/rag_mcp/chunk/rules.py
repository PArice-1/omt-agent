"""各文件类型的固定递归规则；不调用模型或计算语义相似度。

使用 character tokenizer，chunk_size 的单位为字符。所有分隔符保留在前段，
最终的 RecursiveLevel() 对没有分隔符的超长内容按字符数切分。
"""

from chonkie import RecursiveLevel, RecursiveRules

DEFAULT_CHUNK_SIZE = 2048
MIN_CHARACTERS_PER_CHUNK = 1

# Markdown 的标题边界先由 markdown.py 按语法识别。单个章节内依次尝试：
# 段落、换行、中英文句末标点、从句标点、空格，最后按字符数切分。
MARKDOWN_RULES = RecursiveRules(
    levels=[
        RecursiveLevel(delimiters=["\r\n\r\n", "\n\n", "\r\r"]),
        RecursiveLevel(delimiters=["\r\n", "\n", "\r"]),
        RecursiveLevel(delimiters=["。", "！", "？", ". ", "! ", "? "]),
        RecursiveLevel(delimiters=["；", "，", "; ", ", "]),
        RecursiveLevel(whitespace=True),
        RecursiveLevel(),
    ]
)

# TXT 不识别标题或 Markdown 语法，单独维护其规则：
# 段落、换行、中英文句末标点、空格，最后按字符数切分。
TEXT_RULES = RecursiveRules(
    levels=[
        RecursiveLevel(delimiters=["\r\n\r\n", "\n\n", "\r\r"]),
        RecursiveLevel(delimiters=["\r\n", "\n", "\r"]),
        RecursiveLevel(delimiters=["。", "！", "？", ". ", "! ", "? "]),
        RecursiveLevel(whitespace=True),
        RecursiveLevel(),
    ]
)
