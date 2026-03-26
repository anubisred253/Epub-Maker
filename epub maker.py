import os
import re
import sys
import html
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


def resource_path(relative_path):
    """读取打包进程序的资源"""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


def app_base_path():
    """程序实际所在目录，用于输出 html"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


class EpubMakerApp:
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

        # 默认目录
        self.base_dir = app_base_path()
        self.template_dir = os.path.join(self.base_dir, "template")
        self.output_dir = os.path.join(self.base_dir, "html")

        os.makedirs(self.template_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

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

        self.btn_generate = ttk.Button(
            right_frame, text="生成HTML", command=self.generate_html
        )
        self.btn_generate.grid(row=3, column=0, sticky="ew", pady=4)

        level_frame = ttk.LabelFrame(right_frame, text="HTML 级别")
        level_frame.grid(row=4, column=0, sticky="ew", pady=(10, 6))
        level_frame.columnconfigure(1, weight=1)

        default_keywords = ["卷", "章", "", ""]
        for idx, default_keyword in enumerate(default_keywords, start=1):
            ttk.Label(level_frame, text=f"H{idx}").grid(
                row=idx - 1, column=0, sticky="w", padx=(6, 4), pady=3
            )
            var = tk.StringVar(value=default_keyword)
            entry = ttk.Entry(level_frame, textvariable=var, width=12)
            entry.grid(row=idx - 1, column=1, sticky="ew", padx=(0, 6), pady=3)
            self.heading_vars[idx] = var

        ttk.Separator(right_frame, orient="horizontal").grid(
            row=5, column=0, sticky="ew", pady=10
        )

        note = (
            "说明：\n"
            "1. 先读取TXT\n"
            "2. 分析章节\n"
            "3. 点击左侧章节定位\n"
            "4. 可直接改中间文本\n"
            "5. 根据层级关键字配置 H1-H4\n"
            "6. 再次分析后生成HTML"
        )
        ttk.Label(right_frame, text=note, justify="left").grid(
            row=6, column=0, sticky="nw"
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
  <title>{{TITLE}}</title>
  <link href="../Styles/main.css" rel="stylesheet" type="text/css"/>
</head>
<body>
  <h2 title="{{TITLE}}"></h2>
  <p class="k2"><span class="k2h">{{CHAPTER_NO}}</span><br/>{{CHAPTER_SUBTITLE}}</p>
  <br/><img src="../Images/line.png"/><br/><br/>
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

    def safe_filename(self, seq, title):
        return f"{seq}.html"

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
    # 生成 HTML
    # =========================
    def generate_html(self):
        if not self.items:
            messagebox.showwarning("提示", "请先分析章节。")
            return

        heading_configs = self.get_heading_configs()
        if not heading_configs:
            return

        current_text = self.get_text_from_widget()
        self.current_text = current_text
        lines = current_text.split("\n")

        group_template_path, content_template_path = self.get_template_paths()

        if not os.path.exists(group_template_path):
            messagebox.showerror("模板缺失", "缺少模板文件：template/group.html")
            return
        if not os.path.exists(content_template_path):
            messagebox.showerror("模板缺失", "缺少模板文件：template/content.html")
            return

        with open(group_template_path, "r", encoding="utf-8") as f:
            group_template = f.read()
        with open(content_template_path, "r", encoding="utf-8") as f:
            content_template = f.read()

        # 清空输出目录中的旧 html 文件（只删 html）
        for name in os.listdir(self.output_dir):
            if name.lower().endswith(".html") or name.lower().endswith(".xhtml"):
                try:
                    os.remove(os.path.join(self.output_dir, name))
                except Exception:
                    pass

        for idx, item in enumerate(self.items):
            start_line = item["start_line"]

            if idx + 1 < len(self.items):
                end_line = self.items[idx + 1]["start_line"]
            else:
                end_line = len(lines)

            block_lines = lines[start_line:end_line]
            if not block_lines:
                continue

            title_line = block_lines[0].strip()

            body_lines = block_lines[1:]  # 去掉标题行
            paragraphs = []
            for line in body_lines:
                t = line.strip()
                if t:
                    paragraphs.append(t)

            if item["level"] == 1 and not paragraphs:
                html_content = self.render_group(group_template, item["title"])
                filename = self.safe_filename(item["seq"], item["title"])
                out_path = os.path.join(self.output_dir, filename)
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(html_content)
            else:
                html_content = self.render_content(
                    content_template=content_template,
                    full_title=item["title"],
                    heading_tag=f'h{min(item["level"], 6)}',
                    chapter_no=item["prefix"] or title_line,
                    chapter_subtitle=item["subtitle"] or "",
                    paragraphs=paragraphs,
                )
                filename = self.safe_filename(item["seq"], item["title"])
                out_path = os.path.join(self.output_dir, filename)
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(html_content)

        messagebox.showinfo("完成", f"HTML 已输出到目录：\n{self.output_dir}")

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
