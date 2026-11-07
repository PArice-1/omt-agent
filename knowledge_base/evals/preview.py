"""预览数据与一组标准对应关系，不执行模型检索或效果评分。"""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .datasets import T2Retrieval

DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data"


def main() -> None:
    parser = argparse.ArgumentParser(description="检查 T2Retrieval 文件并预览标准相关资料")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="Parquet 文件目录")
    parser.add_argument("--batch-size", type=int, default=1000, help="每批读取记录数")
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size 必须是正整数")

    dataset = T2Retrieval(args.data_dir)
    print(f"数据目录：{dataset.data_dir}")
    print("记录数量：", json.dumps(dataset.counts, ensure_ascii=False))
    example = dataset.first_example(batch_size=args.batch_size)
    print("\n第一道有正相关标注的问题及其全部相关资料：")
    print(json.dumps(asdict(example), ensure_ascii=False, indent=2))
    print("\n以上是标准标注，不是模型搜索结果；本步骤没有调用 embedding，也没有计算评估指标。")


if __name__ == "__main__":
    main()
