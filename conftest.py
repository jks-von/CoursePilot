"""确保测试运行时能够以项目根目录为基准导入 agent / document / utils 等模块。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
