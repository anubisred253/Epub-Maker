import os
import re
import sys
import html
import shutil
import zipfile
import tempfile
import uuid
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

# 作者：龙骑兵


def resource_path(relative_path):
    """读取打包进程序的资源"""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


def app_base_path():
    """程序实际所在目录，用于输出文件"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


class EpubMakerApp:
    MANUAL_HEADING_PATTERN = re.compile(r"^【--([1-4])】(.+)$")
    MANUAL_NON_HEADING_PREFIX = "【==】"

    def __init__(self, root):
        self.root = root
        self.root.title("Epub Maker")
        self.root.geometry("1300x780")

        # 使用资源路径函数设置窗口图标
        icon_path = resource_path("epub maker.ico")
        self.root.iconbitmap(icon_path)

        # 当前内存文本、文件名、解析结果
        self.current_text = ""
        self.current_file = ""
        self.items = []  # 卷/章结构列表
        self.line_offsets = []  # 每行在全文中的字符起始位置，便于跳转

        # 搜索状态
        self.search_results = []
        self.search_index = -1
        self.search_keyword = ""
        self.heading_vars = {}
        self.book_title_var = tk.StringVar()
        self.book_author_var = tk.StringVar()
        self.book_subject_var = tk.StringVar()
        self.cover_image_var = tk.StringVar(value="未选择封面")
        self.cover_image_path = ""

        # 默认目录
        self.base_dir = app_base_path()
        self.template_dir = os.path.join(self.base_dir, "template")
        self.template_epub_path = os.path.join(self.base_dir, "模板.epub")
        self.epub_output_dir = os.path.join(self.base_dir, "epub")

        os.makedirs(self.template_dir, exist_ok=True)
        os.makedirs(self.epub_output_dir, exist_ok=True)

        self.build_ui()
        self.ensure_default_templates()

    # =========================
    # UI
    # =========================
    def build_ui(self):
        self.root.rowconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=0)
        self.root.columnconfigure(0, weight=1)

        main_frame = ttk.Frame(self.root, padding=8)
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=0)  # 左
        main_frame.columnconfigure(1, weight=1)  # 中
        main_frame.columnconfigure(2, weight=0)  # 右

        # 左侧 Treeview
        left_frame = ttk.Frame(main_frame)
        left_frame.grid(row=0, column=0, sticky="nsw", padx=(0, 8))
        left_frame.rowconfigure(1, weight=1)
        left_frame.columnconfigure(0, weight=1)

        ttk.Label(left_frame, text="章节结构").grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )

        tree_container = ttk.Frame(left_frame)
        tree_container.grid(row=1, column=0, sticky="nsew")
        tree_container.rowconfigure(0, weight=1)
        tree_container.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            tree_container,
            columns=("seq", "level", "title", "warn"),
            show="headings",
            height=30,
        )
        self.tree.heading("seq", text="编号")
        self.tree.heading("level", text="级别")
        self.tree.heading("title", text="标题")
        self.tree.heading("warn", text="预警")

        self.tree.column("seq", width=70, anchor="center", stretch=False)
        self.tree.column("level", width=60, anchor="center", stretch=False)
        self.tree.column("title", width=240, anchor="w", stretch=True)
        self.tree.column("warn", width=50, anchor="center", stretch=False)

        tree_scroll = ttk.Scrollbar(
            tree_container, orient="vertical", command=self.tree.yview
        )
        self.tree.configure(yscrollcommand=tree_scroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll.grid(row=0, column=1, sticky="ns")

        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        # 中间 Text
        center_frame = ttk.Frame(main_frame)
        center_frame.grid(row=0, column=1, sticky="nsew", padx=(0, 8))
        center_frame.rowconfigure(1, weight=1)
        center_frame.columnconfigure(0, weight=1)

        ttk.Label(center_frame, text="TXT全文").grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )

        text_container = ttk.Frame(center_frame)
        text_container.grid(row=1, column=0, sticky="nsew")
        text_container.rowconfigure(0, weight=1)
        text_container.columnconfigure(0, weight=1)

        search_frame = ttk.Frame(center_frame)
        search_frame.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        search_frame.columnconfigure(1, weight=1)

        ttk.Label(search_frame, text="搜索").grid(row=0, column=0, padx=(0, 6))

        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        self.search_entry.grid(row=0, column=1, sticky="ew")
        self.search_entry.bind("<Return>", lambda event: self.search_text())

        self.btn_search = ttk.Button(
            search_frame, text="搜索", command=self.search_text
        )
        self.btn_search.grid(row=0, column=2, padx=4)

        self.btn_prev = ttk.Button(
            search_frame, text="上一个", command=self.search_prev
        )
        self.btn_prev.grid(row=0, column=3, padx=4)

        self.btn_next = ttk.Button(
            search_frame, text="下一个", command=self.search_next
        )
        self.btn_next.grid(row=0, column=4, padx=4)

        self.search_status_var = tk.StringVar(value="0/0")
        ttk.Label(
            search_frame, textvariable=self.search_status_var, width=10, anchor="center"
        ).grid(row=0, column=5, padx=(8, 0))

        self.text_widget = tk.Text(
            text_container, wrap="word", undo=True, font=("微软雅黑", 12)
        )

        self.text_widget.tag_configure("current_line", background="#fff2a8")
        self.text_widget.tag_configure("title_line", foreground="#003366")
        self.text_widget.tag_configure("search_hit", background="#cfe8ff")
        self.text_widget.tag_configure("search_current", background="#7cc5ff")

        text_scroll_y = ttk.Scrollbar(
            text_container, orient="vertical", command=self.text_widget.yview
        )
        text_scroll_x = ttk.Scrollbar(
            text_container, orient="horizontal", command=self.text_widget.xview
        )
        self.text_widget.configure(
            yscrollcommand=text_scroll_y.set, xscrollcommand=text_scroll_x.set
        )

        self.text_widget.grid(row=0, column=0, sticky="nsew")
        text_scroll_y.grid(row=0, column=1, sticky="ns")
        text_scroll_x.grid(row=1, column=0, sticky="ew")

        # 右侧按钮
        right_frame = ttk.Frame(main_frame)
        right_frame.grid(row=0, column=2, sticky="nse", padx=(0, 0))
        right_frame.columnconfigure(0, weight=1)

        ttk.Label(right_frame, text="操作").grid(
            row=0, column=0, sticky="w", pady=(0, 10)
        )

        self.btn_open = ttk.Button(right_frame, text="读取TXT", command=self.load_txt)
        self.btn_open.grid(row=1, column=0, sticky="ew", pady=4)

        self.btn_analyze = ttk.Button(
            right_frame, text="分析章节", command=self.analyze_text
        )
        self.btn_analyze.grid(row=2, column=0, sticky="ew", pady=4)

        self.btn_save = ttk.Button(right_frame, text="保存TXT", command=self.save_txt)
        self.btn_save.grid(row=3, column=0, sticky="ew", pady=4)

        self.btn_open_folder = ttk.Button(
            right_frame, text="打开文件夹", command=self.open_app_folder
        )
        self.btn_open_folder.grid(row=4, column=0, sticky="ew", pady=4)

        meta_frame = ttk.LabelFrame(right_frame, text="生成 EPUB")
        meta_frame.grid(row=5, column=0, sticky="ew", pady=(10, 6))
        meta_frame.columnconfigure(1, weight=1)

        ttk.Label(meta_frame, text="标题").grid(
            row=0, column=0, sticky="w", padx=(6, 4), pady=3
        )
        ttk.Entry(meta_frame, textvariable=self.book_title_var, width=18).grid(
            row=0, column=1, sticky="ew", padx=(0, 6), pady=3
        )

        ttk.Label(meta_frame, text="作者").grid(
            row=1, column=0, sticky="w", padx=(6, 4), pady=3
        )
        ttk.Entry(meta_frame, textvariable=self.book_author_var, width=18).grid(
            row=1, column=1, sticky="ew", padx=(0, 6), pady=3
        )

        ttk.Label(meta_frame, text="分类").grid(
            row=2, column=0, sticky="w", padx=(6, 4), pady=3
        )
        ttk.Entry(meta_frame, textvariable=self.book_subject_var, width=18).grid(
            row=2, column=1, sticky="ew", padx=(0, 6), pady=3
        )

        ttk.Button(
            meta_frame, text="选择封面图片", command=self.choose_cover_image
        ).grid(row=3, column=0, columnspan=2, sticky="ew", padx=6, pady=(6, 3))
        ttk.Label(
            meta_frame,
            textvariable=self.cover_image_var,
            justify="left",
            wraplength=180,
        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=6, pady=(0, 6))

        self.btn_generate_epub = ttk.Button(
            meta_frame, text="生成EPUB", command=self.generate_epub
        )
        self.btn_generate_epub.grid(
            row=5, column=0, columnspan=2, sticky="ew", padx=6, pady=(0, 6)
        )

        level_frame = ttk.LabelFrame(right_frame, text="标题级别")
        level_frame.grid(row=6, column=0, sticky="ew", pady=(10, 6))
        level_frame.columnconfigure(1, weight=1)

        default_keywords = ["章", "", "", ""]
        for idx, default_keyword in enumerate(default_keywords, start=1):
            ttk.Label(level_frame, text=f"H{idx}").grid(
                row=idx - 1, column=0, sticky="w", padx=(6, 4), pady=3
            )
            var = tk.StringVar(value=default_keyword)
            entry = ttk.Entry(level_frame, textvariable=var, width=12)
            entry.grid(row=idx - 1, column=1, sticky="ew", padx=(0, 6), pady=3)
            self.heading_vars[idx] = var

        ttk.Separator(right_frame, orient="horizontal").grid(
            row=7, column=0, sticky="ew", pady=10
        )

        note = (
            "说明：\n"
            "1. 读取TXT，分析章节\n"
            "2. 点击左侧章节定位，直接修改中间文本\n"
            "3. 根据层级关键字配置 H1-H4\n"
            "4. 生成EPUB\n"
            "5. 使用【--1】到【--4】手动标注 H1-H4\n"
            "6. 使用【==】强制标注为非章节"
        )
        ttk.Label(right_frame, text=note, justify="left").grid(
            row=8, column=0, sticky="nw"
        )
        repo_link = tk.Label(
            right_frame,
            text="当前版本：1.0.0  点击访问项目主页",
            fg="#1a73e8",
            cursor="hand2",
            anchor="w",
            justify="left",
        )
        repo_link.grid(row=9, column=0, sticky="nw", pady=(6, 0))
        repo_link.bind(
            "<Button-1>",
            lambda _event: webbrowser.open(
                "https://github.com/anubisred253/Epub-Maker"
            ),
        )

        # 底部状态栏
        status_frame = ttk.Frame(self.root, padding=(8, 0, 8, 8))
        status_frame.grid(row=1, column=0, sticky="ew")
        status_frame.columnconfigure(0, weight=1)

        self.status_var = tk.StringVar()
        self.status_var.set("未加载TXT")
        ttk.Label(status_frame, textvariable=self.status_var, anchor="w").grid(
            row=0, column=0, sticky="ew"
        )

    # =========================
    # 默认模板
    # =========================
    def ensure_default_templates(self):
        group_path = os.path.join(self.template_dir, "group.html")
        content_path = os.path.join(self.template_dir, "content.html")

        if not os.path.exists(group_path):
            group_template = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
  "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN" xmlns:xml="http://www.w3.org/XML/1998/namespace">
<head>
  <meta name="right" content="该文档由epub maker生成，作者：龙骑兵。为里屋论坛（https://www.253874.net/）提供的epub制作工具，仅供个人交流与学习使用，未获得龙骑兵商业授权前，不得用于任何商业用途。"/>
  <title>{{TITLE}}</title>
  <link href="../Styles/main.css" rel="stylesheet" type="text/css"/>
</head>
<body>
  <h1 title="{{TITLE}}"></h1>
  <p class="k1">{{TITLE}}</p>
</body>
</html>
"""
            with open(group_path, "w", encoding="utf-8") as f:
                f.write(group_template)

        if not os.path.exists(content_path):
            content_template = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
  "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN" xmlns:xml="http://www.w3.org/XML/1998/namespace">
<head>
  <meta name="right" content="该文档由epub maker生成，作者：龙骑兵。为里屋论坛（https://www.253874.net/）提供的epub制作工具，仅供个人交流与学习使用，未获得龙骑兵商业授权前，不得用于任何商业用途。"/>
  <title>{{TITLE}}</title>
  <link href="../Styles/main.css" rel="stylesheet" type="text/css"/>
</head>
<body>
  <h2 title="{{TITLE}}"></h2>
  <p class="k2"><span class="k2h">{{CHAPTER_NO}}</span><br/>{{CHAPTER_SUBTITLE}}</p>
{{CONTENT}}
</body>
</html>
"""
            with open(content_path, "w", encoding="utf-8") as f:
                f.write(content_template)

    def get_template_paths(self):
        group_path = os.path.join(self.template_dir, "group.html")
        content_path = os.path.join(self.template_dir, "content.html")
        return group_path, content_path

    # =========================
    # 工具函数
    # =========================
    def update_status(self):
        filename = (
            os.path.basename(self.current_file) if self.current_file else "未加载"
        )
        if not self.items:
            self.status_var.set(f"文件：{filename}    标题数：0    预警数：0")
            return

        level_counts = {}
        for item in self.items:
            level_counts[item["level"]] = level_counts.get(item["level"], 0) + 1

        warning_count = sum(1 for item in self.items if item["warning"])
        level_parts = [
            f"H{level}：{level_counts[level]}" for level in sorted(level_counts)
        ]
        self.status_var.set(
            f"文件：{filename}    标题数：{len(self.items)}    预警数：{warning_count}    "
            + "    ".join(level_parts)
        )

    def get_text_from_widget(self):
        return self.text_widget.get("1.0", "end-1c")

    def set_text_to_widget(self, text):
        self.text_widget.delete("1.0", "end")
        self.text_widget.insert("1.0", text)
        self.current_text = text
        self.rebuild_line_offsets()

    def rebuild_line_offsets(self):
        lines = self.current_text.splitlines(True)  # 保留换行
        self.line_offsets = []
        offset = 0
        for line in lines:
            self.line_offsets.append(offset)
            offset += len(line)

    def line_to_text_index(self, line_no):
        # line_no 从 0 开始
        return f"{line_no + 1}.0"

    def clear_highlight(self):
        self.text_widget.tag_remove("current_line", "1.0", "end")

    def highlight_line(self, line_no):
        self.clear_highlight()
        idx_start = self.line_to_text_index(line_no)
        idx_end = f"{line_no + 1}.end"
        self.text_widget.tag_add("current_line", idx_start, idx_end)
        self.text_widget.tag_remove("sel", "1.0", "end")
        self.text_widget.mark_set("insert", idx_start)
        self.text_widget.see(idx_start)
        self.text_widget.focus_set()

    def safe_output_name(self, name, default):
        cleaned = re.sub(r'[\\/:*?"<>|]+', "_", name.strip())
        cleaned = cleaned.rstrip(". ")
        return cleaned or default

    def choose_cover_image(self):
        path = filedialog.askopenfilename(
            title="选择封面图片",
            filetypes=[
                ("Image Files", "*.jpg;*.jpeg;*.png;*.webp;*.bmp"),
                ("All Files", "*.*"),
            ],
        )
        if not path:
            return

        self.cover_image_path = path
        self.cover_image_var.set(os.path.basename(path))

    def get_book_metadata(self):
        title = self.book_title_var.get().strip()
        author = self.book_author_var.get().strip()
        subject_raw = self.book_subject_var.get().strip()

        if not title:
            messagebox.showwarning("提示", "请填写标题。")
            return None

        subjects = [
            item.strip() for item in re.split(r"[，,]", subject_raw) if item.strip()
        ]

        return {
            "title": title,
            "author": author,
            "subjects": subjects,
        }

    def collect_sections(self):
        if not self.items:
            return []

        current_text = self.get_text_from_widget()
        self.current_text = current_text
        lines = current_text.split("\n")
        sections = []

        for idx, item in enumerate(self.items):
            start_line = item["start_line"]
            end_line = (
                self.items[idx + 1]["start_line"]
                if idx + 1 < len(self.items)
                else len(lines)
            )
            block_lines = lines[start_line:end_line]
            if not block_lines:
                continue

            title_line = self.strip_manual_non_heading_marker(block_lines[0]).strip()
            paragraphs = [
                self.strip_manual_non_heading_marker(line).strip()
                for line in block_lines[1:]
                if self.strip_manual_non_heading_marker(line).strip()
            ]
            sections.append(
                {
                    "item": item,
                    "title_line": title_line,
                    "paragraphs": paragraphs,
                    "is_group": item["level"] == 1 and not paragraphs,
                }
            )

        return sections

    def get_heading_configs(self):
        configs = []
        seen_keywords = set()

        for level in sorted(self.heading_vars):
            keyword = self.heading_vars[level].get().strip()
            if not keyword:
                continue
            if keyword in seen_keywords:
                messagebox.showwarning(
                    "提示", f"H{level} 的关键字与其他级别重复：{keyword}"
                )
                return None
            seen_keywords.add(keyword)
            configs.append({"level": level, "keyword": keyword})

        if not configs:
            messagebox.showwarning("提示", "请至少填写 1 个层级关键字。")
            return None

        return configs

    def split_title(self, title_line, keyword):
        """
        返回:
        prefix = 第九章
        subtitle = 二面
        full_title = 第九章 二面 或 第九章
        number = 9（用于连续性检查，尽量转换，失败则 None）
        """
        pattern = rf"^(第[一二三四五六七八九十百千万零〇两\d]+{re.escape(keyword)})(?:\s+(.*))?$"

        m = re.match(pattern, title_line.strip())
        if not m:
            return None, None, title_line.strip(), None

        prefix = m.group(1).strip()
        subtitle = (m.group(2) or "").strip()
        full_title = prefix if not subtitle else f"{prefix} {subtitle}"
        number = self.extract_cn_number(prefix)
        return prefix, subtitle, full_title, number

    def is_manual_heading_title(self, line):
        line = line.strip()
        match = self.MANUAL_HEADING_PATTERN.match(line)
        return bool(match and match.group(2).strip())

    def is_manual_non_heading(self, line):
        return line.strip().startswith(self.MANUAL_NON_HEADING_PREFIX)

    def strip_manual_non_heading_marker(self, line):
        leading_match = re.match(r"^(\s*)", line)
        leading = leading_match.group(1) if leading_match else ""
        content = line[len(leading) :]
        if content.startswith(self.MANUAL_NON_HEADING_PREFIX):
            return leading + content[len(self.MANUAL_NON_HEADING_PREFIX) :].lstrip()
        return line

    def split_manual_heading_title(self, title_line):
        match = self.MANUAL_HEADING_PATTERN.match(title_line.strip())
        if not match:
            return 1, "", ""
        level = int(match.group(1) or 1)
        title = match.group(2).strip()
        return level, title, title

    def extract_cn_number(self, text):
        m = re.search(r"第([一二三四五六七八九十百千万零〇两\d]+)", text)
        if not m:
            return None
        s = m.group(1)
        if s.isdigit():
            return int(s)
        return self.chinese_to_int(s)

    def chinese_to_int(self, s):
        # 支持常见中文数字，足够用于章节判断
        digit_map = {
            "零": 0,
            "〇": 0,
            "一": 1,
            "二": 2,
            "两": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
        }
        unit_map = {"十": 10, "百": 100, "千": 1000, "万": 10000}

        if not s:
            return None

        total = 0
        section = 0
        number = 0

        for ch in s:
            if ch in digit_map:
                number = digit_map[ch]
            elif ch in unit_map:
                unit = unit_map[ch]
                if unit == 10000:
                    section = (section + (number if number != 0 else 0)) * unit
                    total += section
                    section = 0
                    number = 0
                else:
                    if number == 0:
                        number = 1
                    section += number * unit
                    number = 0
            else:
                return None

        return total + section + number

    def is_heading_title(self, line, keyword):
        line = line.strip()
        if not line:
            return False
        if len(line) > 30:
            return False
        pattern = (
            rf"^第[一二三四五六七八九十百千万零〇两\d]+{re.escape(keyword)}(?:\s*.*)?$"
        )
        return re.match(pattern, line) is not None

    def has_suspicious_title_tail(self, line):
        keywords = [
            "求订阅",
            "求月票",
            "求推荐票",
            "补昨天",
            "补更",
            "加更",
            "今日",
            "二更",
            "三更",
            "四更",
            "五更",
            "上架感言",
            "感谢",
            "PS",
            "ps",
            "读者",
            "请假",
        ]
        return any(k in line for k in keywords)

    def next_line_starts_with_punct(self, lines, index, heading_configs):
        if index + 1 >= len(lines):
            return False

        next_line = lines[index + 1].strip()
        if not next_line:
            return False

        for config in heading_configs:
            if self.is_heading_title(next_line, config["keyword"]):
                return False

        suspicious_prefixes = (
            "！",
            "？",
            "…",
            "——",
            "—",
            "）",
            "】",
            "”",
            "」",
            "』",
            "：",
            "、",
            ".",
            "。",
        )
        return next_line.startswith(suspicious_prefixes)

    # =========================
    # 功能：读取TXT
    # =========================
    def load_txt(self):
        path = filedialog.askopenfilename(
            title="选择TXT文件",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
        )
        if not path:
            return

        encodings = ["utf-8", "utf-8-sig", "gb18030", "gbk", "big5"]
        text = None
        for enc in encodings:
            try:
                with open(path, "r", encoding=enc) as f:
                    text = f.read()
                break
            except UnicodeDecodeError:
                continue
            except Exception as e:
                messagebox.showerror("读取失败", f"读取文件时出错：\n{e}")
                return

        if text is None:
            messagebox.showerror("读取失败", "无法识别该TXT文件编码。")
            return

        text = text.replace("\r\n", "\n").replace("\r", "\n")

        self.current_file = path
        self.items = []
        self.set_text_to_widget(text)
        self.refresh_tree()
        self.update_status()
        messagebox.showinfo("成功", "TXT 已加载到内存。")

    def save_txt(self):
        text = self.get_text_from_widget()
        if not text.strip():
            messagebox.showwarning("提示", "当前没有可保存的文本。")
            return

        path = self.current_file
        if not path:
            path = filedialog.asksaveasfilename(
                title="保存TXT文件",
                defaultextension=".txt",
                filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
                initialdir=self.base_dir,
            )
            if not path:
                return

        text = text.replace("\r\n", "\n").replace("\r", "\n")

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as e:
            messagebox.showerror("保存失败", f"保存文件时出错：\n{e}")
            return

        self.current_file = path
        self.current_text = text
        self.rebuild_line_offsets()
        self.update_status()
        messagebox.showinfo("成功", f"TXT 已保存：\n{path}")

    # =========================
    # 功能：分析章节
    # =========================
    def analyze_text(self):
        text = self.get_text_from_widget()
        if not text.strip():
            messagebox.showwarning("提示", "当前没有可分析的文本。")
            return

        heading_configs = self.get_heading_configs()
        if not heading_configs:
            return

        self.current_text = text
        self.rebuild_line_offsets()

        lines = text.split("\n")
        found = []
        seq_counter = 1
        prev_numbers = {}
        parent_titles = {}

        for i, raw_line in enumerate(lines):
            line = raw_line.strip()
            if not line:
                continue

            if self.is_manual_non_heading(line):
                continue

            if self.is_manual_heading_title(line):
                level, prefix, full_title = self.split_manual_heading_title(line)
                if not full_title:
                    continue

                warning = ""
                if self.has_suspicious_title_tail(
                    full_title
                ) or self.next_line_starts_with_punct(lines, i, heading_configs):
                    warning = "⚠"

                prev_numbers.pop(level, None)
                for lower_level in list(prev_numbers):
                    if lower_level > level:
                        prev_numbers.pop(lower_level, None)

                parent_title = None
                parent_titles[level] = full_title
                for lower_level in list(parent_titles):
                    if lower_level > level:
                        parent_titles.pop(lower_level, None)

                found.append(
                    {
                        "type": "manual-heading",
                        "level": level,
                        "keyword": f"【--{level}】",
                        "seq": f"{seq_counter:04d}",
                        "title": full_title,
                        "prefix": prefix,
                        "subtitle": "",
                        "warning": warning,
                        "start_line": i,
                        "number": None,
                        "parent_title": parent_title,
                    }
                )
                seq_counter += 1
                continue

            matched_config = None
            for config in heading_configs:
                if self.is_heading_title(line, config["keyword"]):
                    matched_config = config
                    break

            if not matched_config:
                continue

            level = matched_config["level"]
            prefix, subtitle, full_title, number = self.split_title(
                line, matched_config["keyword"]
            )
            warning = ""
            prev_number = prev_numbers.get(level)
            if (
                prev_number is not None
                and number is not None
                and number != prev_number + 1
            ):
                warning = "⚠"
            if self.has_suspicious_title_tail(line) or self.next_line_starts_with_punct(
                lines, i, heading_configs
            ):
                warning = "⚠"

            prev_numbers[level] = number
            for lower_level in list(prev_numbers):
                if lower_level > level:
                    prev_numbers.pop(lower_level, None)

            parent_title = parent_titles.get(level - 1)
            parent_titles[level] = full_title
            for lower_level in list(parent_titles):
                if lower_level > level:
                    parent_titles.pop(lower_level, None)

            found.append(
                {
                    "type": "heading",
                    "level": level,
                    "keyword": matched_config["keyword"],
                    "seq": f"{seq_counter:04d}",
                    "title": full_title,
                    "prefix": prefix,
                    "subtitle": subtitle,
                    "warning": warning,
                    "start_line": i,
                    "number": number,
                    "parent_title": parent_title,
                }
            )
            seq_counter += 1

        self.items = found
        self.refresh_tree()
        self.update_status()

        if not self.items:
            messagebox.showwarning("结果", "没有识别到卷或章。请检查TXT格式。")
        else:
            messagebox.showinfo(
                "完成", f"分析完成，共识别到 {len(self.items)} 个卷/章项。"
            )

    def refresh_tree(self):
        for child in self.tree.get_children():
            self.tree.delete(child)

        for idx, item in enumerate(self.items):
            self.tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    item["seq"],
                    f'H{item["level"]}',
                    item["title"],
                    item["warning"],
                ),
            )

    # =========================
    # 点击 Treeview 定位
    # =========================
    def on_tree_select(self, event):
        selection = self.tree.selection()
        if not selection:
            return

        idx = int(selection[0])
        if idx < 0 or idx >= len(self.items):
            return

        item = self.items[idx]
        line_no = item["start_line"]
        self.highlight_line(line_no)

    # =========================
    # =========================
    def build_rendered_documents(
        self, sections, group_template, content_template, extension
    ):
        documents = []
        for section in sections:
            item = section["item"]
            filename = f'{item["seq"]}.{extension}'
            if section["is_group"]:
                content = self.render_group(group_template, item["title"])
            else:
                content = self.render_content(
                    content_template=content_template,
                    full_title=item["title"],
                    heading_tag=f'h{min(item["level"], 6)}',
                    chapter_no=item["prefix"] or section["title_line"],
                    chapter_subtitle=item["subtitle"] or "",
                    paragraphs=section["paragraphs"],
                )

            documents.append(
                {
                    "filename": filename,
                    "content": content,
                    "level": item["level"],
                    "title": item["title"],
                }
            )
        return documents

    def get_cover_info(self):
        if not self.cover_image_path:
            return None

        source_ext = os.path.splitext(self.cover_image_path)[1].lower()
        ext_map = {
            ".jpg": (".jpg", "image/jpeg"),
            ".jpeg": (".jpg", "image/jpeg"),
            ".png": (".png", "image/png"),
            ".webp": (".webp", "image/webp"),
            ".bmp": (".bmp", "image/bmp"),
        }
        if source_ext not in ext_map:
            messagebox.showwarning("提示", "封面图片仅支持 jpg、png、webp、bmp。")
            return None

        output_ext, media_type = ext_map[source_ext]
        filename = f"cover{output_ext}"
        return {
            "source_path": self.cover_image_path,
            "filename": filename,
            "href": f"Images/{filename}",
            "src": f"../Images/{filename}",
            "media_type": media_type,
        }

    def generate_epub(self):
        if not self.items:
            messagebox.showwarning("提示", "请先分析章节。")
            return

        metadata = self.get_book_metadata()
        if not metadata:
            return

        cover_info = self.get_cover_info()

        if not os.path.exists(self.template_epub_path):
            messagebox.showerror(
                "模板缺失", f"缺少模板文件：\n{self.template_epub_path}"
            )
            return

        group_template_path, content_template_path = self.get_template_paths()
        if not os.path.exists(group_template_path) or not os.path.exists(
            content_template_path
        ):
            messagebox.showerror("模板缺失", "缺少 HTML 模板文件。")
            return

        with open(group_template_path, "r", encoding="utf-8") as f:
            group_template = f.read()
        with open(content_template_path, "r", encoding="utf-8") as f:
            content_template = f.read()

        sections = self.collect_sections()
        if not sections:
            messagebox.showwarning("提示", "没有可导出的章节内容。")
            return

        documents = self.build_rendered_documents(
            sections, group_template, content_template, extension="xhtml"
        )

        temp_dir = tempfile.mkdtemp(prefix="epub-maker-", dir=self.base_dir)
        try:
            self.extract_epub_template(self.template_epub_path, temp_dir)
            self.write_epub_contents(temp_dir, metadata, cover_info, documents)

            output_name = self.safe_output_name(metadata["title"], "book")
            output_path = os.path.join(self.epub_output_dir, f"{output_name}.epub")
            self.pack_epub(temp_dir, output_path)
        except Exception as exc:
            messagebox.showerror("生成失败", f"生成 EPUB 时出错：\n{exc}")
            return
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        messagebox.showinfo("完成", f"EPUB 已输出到目录：\n{output_path}")

    def extract_epub_template(self, epub_path, target_dir):
        with zipfile.ZipFile(epub_path, "r") as zf:
            zf.extractall(target_dir)

    def write_epub_contents(self, root_dir, metadata, cover_info, documents):
        oebps_dir = os.path.join(root_dir, "OEBPS")
        text_dir = os.path.join(oebps_dir, "Text")
        images_dir = os.path.join(oebps_dir, "Images")
        os.makedirs(text_dir, exist_ok=True)
        os.makedirs(images_dir, exist_ok=True)

        self.cleanup_old_text_files(text_dir)
        self.cleanup_old_cover_images(images_dir)

        for document in documents:
            out_path = os.path.join(text_dir, document["filename"])
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(document["content"])

        if cover_info:
            cover_output_path = os.path.join(images_dir, cover_info["filename"])
            shutil.copyfile(cover_info["source_path"], cover_output_path)

        coverpage_path = os.path.join(text_dir, "coverpage.xhtml")
        nav_path = os.path.join(text_dir, "nav.xhtml")
        opf_path = os.path.join(oebps_dir, "content.opf")

        self.update_coverpage(
            coverpage_path, metadata["title"], cover_info["src"] if cover_info else None
        )
        self.update_nav(nav_path, documents)
        self.update_content_opf(opf_path, metadata, cover_info, documents)

    def cleanup_old_text_files(self, text_dir):
        for name in os.listdir(text_dir):
            lower_name = name.lower()
            if not lower_name.endswith((".html", ".xhtml")):
                continue
            if lower_name in {"coverpage.xhtml", "nav.xhtml"}:
                continue
            try:
                os.remove(os.path.join(text_dir, name))
            except Exception:
                pass

    def cleanup_old_cover_images(self, images_dir):
        for name in os.listdir(images_dir):
            lower_name = name.lower()
            if not lower_name.startswith("cover."):
                continue
            try:
                os.remove(os.path.join(images_dir, name))
            except Exception:
                pass

    def update_coverpage(self, coverpage_path, book_title, cover_src):
        with open(coverpage_path, "r", encoding="utf-8") as f:
            content = f.read()

        escaped_title = html.escape(book_title)

        content, title_count = re.subn(
            r"(<title>).*?(</title>)",
            lambda m: f"{m.group(1)}{escaped_title}{m.group(2)}",
            content,
            count=1,
            flags=re.S,
        )

        if title_count == 0:
            raise RuntimeError("模板中的 coverpage.xhtml 缺少 title 节点。")

        content = re.sub(
            r'(<h1\b[^>]*\btitle=")[^"]*(")',
            lambda m: f"{m.group(1)}{html.escape(book_title, quote=True)}{m.group(2)}",
            content,
            count=1,
            flags=re.S,
        )

        if cover_src:
            escaped_src = html.escape(cover_src, quote=True)
            content, img_count = re.subn(
                r'(<img\b[^>]*\bsrc=")[^"]*(")',
                lambda m: f"{m.group(1)}{escaped_src}{m.group(2)}",
                content,
                count=1,
                flags=re.S,
            )
            if img_count == 0:
                raise RuntimeError("模板中的 coverpage.xhtml 缺少封面图片节点。")
        else:
            content = re.sub(
                r"\s*<img\b[^>]*?/?>\s*", "\n", content, count=1, flags=re.S
            )

        with open(coverpage_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)

    def update_nav(self, nav_path, documents):
        with open(nav_path, "r", encoding="utf-8") as f:
            content = f.read()

        content = re.sub(
            r"(<title>).*?(</title>)",
            r"\1目录\2",
            content,
            count=1,
            flags=re.S,
        )
        content = re.sub(
            r'(<html\b[^>]*\blang=")[^"]*(")',
            r"\1zh-CN\2",
            content,
            count=1,
            flags=re.S,
        )
        content = re.sub(
            r'(<html\b[^>]*\bxml:lang=")[^"]*(")',
            r"\1zh-CN\2",
            content,
            count=1,
            flags=re.S,
        )
        content = re.sub(
            r"(<link\b[^>]*\bhref=\")[^\"]*(\"[^>]*>)",
            r"\1../Styles/main.css\2",
            content,
            count=1,
            flags=re.S,
        )
        content = re.sub(
            r"(<nav\b[^>]*epub:type=\"toc\"[^>]*>\s*<h1>).*?(</h1>)",
            r"\1目录\2",
            content,
            count=1,
            flags=re.S,
        )

        nav_html = self.build_nav_html(documents)
        content, toc_count = re.subn(
            r"(<nav\b[^>]*epub:type=\"toc\"[^>]*>.*?<ol>)(.*?)(</ol>)",
            lambda m: f"{m.group(1)}\n{nav_html}\n    {m.group(3)}",
            content,
            count=1,
            flags=re.S,
        )

        if toc_count == 0:
            raise RuntimeError("模板中的 nav.xhtml 缺少目录列表。")

        with open(nav_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)

    def build_nav_tree(self, documents):
        nodes = []
        stack = []
        for document in documents:
            node = {"document": document, "children": []}
            level = max(1, int(document["level"]))

            while stack and stack[-1]["level"] >= level:
                stack.pop()

            if stack:
                stack[-1]["node"]["children"].append(node)
            else:
                nodes.append(node)

            stack.append({"level": level, "node": node})

        return nodes

    def build_nav_html(self, documents):
        tree_nodes = self.build_nav_tree(documents)
        lines = [
            "      <li>",
            '        <a href="coverpage.xhtml">封面</a>',
            "      </li>",
        ]
        lines.extend(self.render_nav_nodes(tree_nodes, indent="      "))
        return "\n".join(lines)

    def render_nav_nodes(self, nodes, indent):
        lines = []
        for node in nodes:
            title = html.escape(node["document"]["title"])
            href = html.escape(node["document"]["filename"], quote=True)
            lines.append(f"{indent}<li>")
            lines.append(f'{indent}  <a href="{href}">{title}</a>')
            if node["children"]:
                lines.append(f"{indent}  <ol>")
                lines.extend(self.render_nav_nodes(node["children"], indent + "    "))
                lines.append(f"{indent}  </ol>")
            lines.append(f"{indent}</li>")
        return lines

    def update_content_opf(self, opf_path, metadata, cover_info, documents):
        opf_ns = "http://www.idpf.org/2007/opf"
        dc_ns = "http://purl.org/dc/elements/1.1/"
        ET.register_namespace("", opf_ns)
        ET.register_namespace("dc", dc_ns)

        tree = ET.parse(opf_path)
        root = tree.getroot()
        metadata_node = root.find(f"{{{opf_ns}}}metadata")
        manifest_node = root.find(f"{{{opf_ns}}}manifest")
        spine_node = root.find(f"{{{opf_ns}}}spine")
        if metadata_node is None or manifest_node is None or spine_node is None:
            raise RuntimeError("模板中的 content.opf 结构不完整。")

        self.set_or_create_dc_text(metadata_node, dc_ns, "language", "zh-CN")
        self.set_or_create_dc_text(metadata_node, dc_ns, "title", metadata["title"])
        self.set_or_create_dc_text(metadata_node, dc_ns, "creator", metadata["author"])
        creator_node = metadata_node.find(f"{{{dc_ns}}}creator")
        if creator_node is not None:
            creator_node.set(f"{{{opf_ns}}}role", "aut")

        for subject_node in list(metadata_node.findall(f"{{{dc_ns}}}subject")):
            metadata_node.remove(subject_node)
        for subject in metadata["subjects"]:
            subject_node = ET.SubElement(metadata_node, f"{{{dc_ns}}}subject")
            subject_node.text = subject

        modified_node = None
        for meta_node in metadata_node.findall(f"{{{opf_ns}}}meta"):
            if meta_node.get("property") == "dcterms:modified":
                modified_node = meta_node
                break
        if modified_node is None:
            modified_node = ET.SubElement(metadata_node, f"{{{opf_ns}}}meta")
            modified_node.set("property", "dcterms:modified")
        modified_node.text = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        cover_item_id = "cover-image"
        nav_id = None
        coverpage_id = None
        for item_node in list(manifest_node.findall(f"{{{opf_ns}}}item")):
            href = item_node.get("href", "")
            item_id = item_node.get("id", "")
            if href.startswith("Text/") and href not in {
                "Text/coverpage.xhtml",
                "Text/nav.xhtml",
            }:
                manifest_node.remove(item_node)
                continue
            if href.startswith("Images/cover"):
                manifest_node.remove(item_node)
                continue
            if href == "Text/nav.xhtml":
                nav_id = item_id
                item_node.set("href", "Text/nav.xhtml")
                item_node.set("media-type", "application/xhtml+xml")
                item_node.set("properties", "nav")
            if href == "Text/coverpage.xhtml":
                coverpage_id = item_id

        if cover_info:
            cover_item = ET.SubElement(manifest_node, f"{{{opf_ns}}}item")
            cover_item.set("id", cover_item_id)
            cover_item.set("href", cover_info["href"])
            cover_item.set("media-type", cover_info["media_type"])
            cover_item.set("properties", "cover-image")

        chapter_ids = []
        for index, document in enumerate(documents, start=1):
            item_node = ET.SubElement(manifest_node, f"{{{opf_ns}}}item")
            item_id = f"chapter-{index:04d}"
            item_node.set("id", item_id)
            item_node.set("href", f'Text/{document["filename"]}')
            item_node.set("media-type", "application/xhtml+xml")
            chapter_ids.append(item_id)

        for itemref_node in list(spine_node.findall(f"{{{opf_ns}}}itemref")):
            spine_node.remove(itemref_node)

        if coverpage_id:
            cover_ref = ET.SubElement(spine_node, f"{{{opf_ns}}}itemref")
            cover_ref.set("idref", coverpage_id)

        for chapter_id in chapter_ids:
            chapter_ref = ET.SubElement(spine_node, f"{{{opf_ns}}}itemref")
            chapter_ref.set("idref", chapter_id)

        if nav_id:
            nav_ref = ET.SubElement(spine_node, f"{{{opf_ns}}}itemref")
            nav_ref.set("idref", nav_id)
            nav_ref.set("linear", "no")

        tree.write(opf_path, encoding="utf-8", xml_declaration=True)
        self.normalize_content_opf(opf_path, opf_ns)

    def set_or_create_dc_text(self, metadata_node, dc_ns, local_name, text):
        node = metadata_node.find(f"{{{dc_ns}}}{local_name}")
        if node is None:
            node = ET.SubElement(metadata_node, f"{{{dc_ns}}}{local_name}")
        node.text = text
        return node

    def pack_epub(self, source_dir, output_path):
        if os.path.exists(output_path):
            os.remove(output_path)

        mimetype_path = os.path.join(source_dir, "mimetype")
        if not os.path.exists(mimetype_path):
            raise RuntimeError("模板中缺少 mimetype 文件。")

        with zipfile.ZipFile(output_path, "w") as zf:
            zf.write(mimetype_path, "mimetype", compress_type=zipfile.ZIP_STORED)
            for root_dir, _, files in os.walk(source_dir):
                for filename in files:
                    full_path = os.path.join(root_dir, filename)
                    rel_path = os.path.relpath(full_path, source_dir).replace("\\", "/")
                    if rel_path == "mimetype":
                        continue
                    zf.write(full_path, rel_path, compress_type=zipfile.ZIP_DEFLATED)

    def normalize_content_opf(self, opf_path, opf_ns):
        with open(opf_path, "r", encoding="utf-8") as f:
            content = f.read()

        if 'xmlns:opf="' not in content:
            content = content.replace(
                "<metadata>",
                f'<metadata xmlns:opf="{opf_ns}">',
                1,
            )

        content = content.replace("<dc:creator role=", "<dc:creator opf:role=")

        with open(opf_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)

    def xhtml_tag(self, local_name):
        return f"{{http://www.w3.org/1999/xhtml}}{local_name}"

    def local_name(self, tag):
        return tag.split("}", 1)[-1]

    def find_first_by_tag(self, root, local_name):
        for node in root.iter():
            if self.local_name(node.tag) == local_name:
                return node
        return None

    def find_child_by_tag(self, root, local_name):
        for node in root:
            if self.local_name(node.tag) == local_name:
                return node
        return None

    def open_app_folder(self):
        if not os.path.isdir(self.base_dir):
            messagebox.showerror("打开失败", f"目录不存在：\n{self.base_dir}")
            return

        try:
            os.startfile(self.base_dir)
        except Exception as exc:
            messagebox.showerror("打开失败", f"无法打开目录：\n{exc}")

    def clear_search_highlight(self):
        self.text_widget.tag_remove("search_hit", "1.0", "end")
        self.text_widget.tag_remove("search_current", "1.0", "end")

    def update_search_status(self):
        total = len(self.search_results)
        if total == 0 or self.search_index < 0:
            self.search_status_var.set("0/0")
        else:
            self.search_status_var.set(f"{self.search_index + 1}/{total}")

    # =========================
    # 搜索功能
    # =========================

    def search_text(self):
        keyword = self.search_var.get().strip()
        self.clear_search_highlight()
        self.search_results = []
        self.search_index = -1
        self.search_keyword = keyword

        if not keyword:
            self.update_search_status()
            return

        start = "1.0"
        while True:
            pos = self.text_widget.search(keyword, start, stopindex="end", nocase=False)
            if not pos:
                break
            end = f"{pos}+{len(keyword)}c"
            self.search_results.append((pos, end))
            self.text_widget.tag_add("search_hit", pos, end)
            start = end

        if self.search_results:
            self.search_index = 0
            self.focus_search_result()
        else:
            self.update_search_status()
            messagebox.showinfo("搜索", f"没有找到：{keyword}")

    def focus_search_result(self):
        if not self.search_results or self.search_index < 0:
            self.update_search_status()
            return

        self.text_widget.tag_remove("search_current", "1.0", "end")

        pos, end = self.search_results[self.search_index]
        self.text_widget.tag_add("search_current", pos, end)
        self.text_widget.tag_remove("sel", "1.0", "end")
        self.text_widget.tag_add("sel", pos, end)
        self.text_widget.mark_set("insert", pos)
        self.text_widget.see(pos)
        self.text_widget.focus_set()

        line_start = f"{pos} linestart"
        line_end = f"{pos} lineend"
        self.text_widget.tag_add("current_line", line_start, line_end)

        self.update_search_status()

    def search_next(self):
        if not self.search_results:
            self.search_text()
            return
        self.search_index = (self.search_index + 1) % len(self.search_results)
        self.focus_search_result()

    def search_prev(self):
        if not self.search_results:
            self.search_text()
            return
        self.search_index = (self.search_index - 1) % len(self.search_results)
        self.focus_search_result()

    # =========================
    # 模板渲染
    # =========================
    def render_group(self, template, title):
        # 优先支持占位符模板
        if "{{TITLE}}" in template:
            return template.replace("{{TITLE}}", html.escape(title))

        # 否则尝试按常见结构替换
        result = template

        result = re.sub(
            r"(<title>).*?(</title>)",
            rf"\1{html.escape(title)}\2",
            result,
            count=1,
            flags=re.S,
        )
        result = re.sub(
            r'(<h1\b[^>]*title=")[^"]*(")',
            rf"\1{html.escape(title)}\2",
            result,
            count=1,
            flags=re.S,
        )
        result = re.sub(
            r"(<h1\b[^>]*></h1>\s*)(<p\b[^>]*class=\"k1\"[^>]*>).*?(</p>)",
            rf"\1\2{html.escape(title)}\3",
            result,
            count=1,
            flags=re.S,
        )
        return result

    def render_content(
        self,
        content_template,
        full_title,
        heading_tag,
        chapter_no,
        chapter_subtitle,
        paragraphs,
    ):
        content_html = "\n".join(
            f'  <p class="lth">{html.escape(p)}</p>' for p in paragraphs
        )

        # 优先支持占位符模板
        if "{{TITLE}}" in content_template:
            result = content_template
            result = result.replace("{{TITLE}}", html.escape(full_title))
            result = result.replace("{{CHAPTER_NO}}", html.escape(chapter_no))
            result = result.replace(
                "{{CHAPTER_SUBTITLE}}", html.escape(chapter_subtitle)
            )
            result = result.replace("{{CONTENT}}", content_html)
            if heading_tag != "h2":
                result = result.replace("<h2 ", f"<{heading_tag} ", 1)
                result = result.replace("</h2>", f"</{heading_tag}>", 1)
            return result

        # 回退：兼容你当前那种固定模板
        result = content_template

        # title
        result = re.sub(
            r"(<title>).*?(</title>)",
            rf"\1{html.escape(full_title)}\2",
            result,
            count=1,
            flags=re.S,
        )

        if heading_tag != "h2":
            result = re.sub(r"<h2\b", f"<{heading_tag}", result, count=1)
            result = re.sub(r"</h2>", f"</{heading_tag}>", result, count=1)

        # h2/h3/h4 title=""
        result = re.sub(
            rf'(<{heading_tag}\b[^>]*title=")[^"]*(")',
            rf"\1{html.escape(full_title)}\2",
            result,
            count=1,
            flags=re.S,
        )

        # <p class="k2"><span class="k2h">第九章</span><br/>二面</p>
        chapter_head_html = (
            f'<p class="k2"><span class="k2h">{html.escape(chapter_no)}</span>'
            f"<br/>{html.escape(chapter_subtitle)}</p>"
            if chapter_subtitle
            else f'<p class="k2"><span class="k2h">{html.escape(chapter_no)}</span></p>'
        )

        result = re.sub(
            r'<p\b[^>]*class="k2"[^>]*>.*?</p>',
            chapter_head_html,
            result,
            count=1,
            flags=re.S,
        )

        # 删除已有正文区：从 k2 标题段之后，到 </body> 之前，保留中间的图片行（如果存在）
        body_match = re.search(
            r"(<p\b[^>]*class=\"k2\"[^>]*>.*?</p>)(.*?)(</body>)", result, flags=re.S
        )
        if body_match:
            middle = body_match.group(2)

            # 尽量保留图片那一行
            img_match = re.search(
                r"(<br\s*/?><img\b[^>]*?/?>.*?<br\s*/?><br\s*/?>)", middle, flags=re.S
            )
            img_block = img_match.group(1) if img_match else "\n"

            replacement = (
                body_match.group(1)
                + img_block
                + "\n"
                + content_html
                + "\n"
                + body_match.group(3)
            )
            result = (
                result[: body_match.start()] + replacement + result[body_match.end() :]
            )

        return result


if __name__ == "__main__":
    root = tk.Tk()
    app = EpubMakerApp(root)
    root.mainloop()
