from __future__ import annotations

import sys
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import os
import platform
import subprocess

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import img2pdf
from PIL import Image


SUPPORTED_EXTS = {".jpg", ".jpeg", ".png"}


def natural_key(p: Path):
    parts = re.split(r"(\d+)", p.name)
    key = []
    for part in parts:
        key.append(int(part) if part.isdigit() else part.lower())
    return tuple(key)


def is_image(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() in SUPPORTED_EXTS


def list_images_in_folder(folder: Path, recursive: bool = False) -> List[Path]:
    pattern = "**/*" if recursive else "*"
    files = [p for p in folder.glob(pattern) if is_image(p)]
    files.sort(key=natural_key)
    return files


def common_parent(paths: List[Path]) -> Path:
    if not paths:
        raise ValueError("paths is empty")
    resolved = [p.resolve() for p in paths]
    # pathlib has no direct commonpath; use os.path.commonpath safely.
    import os
    cp = os.path.commonpath([str(p.parent) if p.is_file() else str(p) for p in resolved])
    return Path(cp)


def convert_images_to_pdf(image_paths: List[Path], output_pdf: Path) -> None:
    """
    화질 저하 최소화를 위해 img2pdf 사용.
    - page_size: 이미지 크기에 맞춰 자동(리사이즈 최소화)
    - fitmode: exact에 가까운 레이아웃(페이지=이미지)
    """
    if not image_paths:
        raise ValueError("변환할 이미지가 없습니다.")

    output_pdf.parent.mkdir(parents=True, exist_ok=True)

    # pagesize=None => 이미지 크기에 맞게 페이지를 구성(가장 안전)
    layout_fun = img2pdf.get_layout_fun(pagesize=None)

    with output_pdf.open("wb") as f:
        f.write(
            img2pdf.convert(
                [str(p) for p in image_paths],
                layout_fun=layout_fun,
                fitmode=img2pdf.FitMode.exact,
            )
        )


def warn_huge_images(image_paths: List[Path]) -> List[str]:
    warnings: List[str] = []
    for p in image_paths:
        try:
            with Image.open(p) as im:
                w, h = im.size
                if w * h >= 40_000_000:  # 40MP 이상
                    warnings.append(f"{p.name} ({w}x{h})")
        except Exception:
            # 열기 실패는 변환 시점에서 에러가 날 수 있으나,
            # 여기서는 경고를 강제하지 않음
            pass
    return warnings


@dataclass
class SelectionState:
    mode: str  # "folder" or "files"
    source: Optional[Path] = None  # folder or common parent
    images: Optional[List[Path]] = None


class ImageToPdfApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("이미지 → PDF 병합 도구")
        self.root.geometry("760x720")
        self.root.configure(bg="#f8f9fa")

        self.state = SelectionState(mode="folder", source=None, images=[])
        self.custom_output_dir: Optional[Path] = None

        self._build_ui()
        self._setup_dnd_if_available()

    def _build_ui(self):
        # 전체 스타일 컨테이너
        main = ttk.Frame(self.root, padding=20)
        main.pack(fill="both", expand=True)

        # 상단 헤더
        header = ttk.Frame(main)
        header.pack(fill="x", pady=(0, 20))

        title = ttk.Label(
            header, text="이미지 → PDF 병합 도구", font=("맑은 고딕", 16, "bold"), foreground="#212529"
        )
        title.pack(anchor="w")

        desc = ttk.Label(
            header,
            text="여러 개의 이미지를 고화질 PDF로 하나로 합칩니다 (img2pdf 사용)",
            font=("맑은 고딕", 10),
            foreground="#6c757d",
        )
        desc.pack(anchor="w", pady=(4, 0))

        # 입력 선택 영역
        sel_box = ttk.LabelFrame(main, text=" 1. 입력 이미지 선택 ", padding=15)
        sel_box.pack(fill="x", pady=(0, 15))

        btn_row = ttk.Frame(sel_box)
        btn_row.pack(fill="x")

        ttk.Button(btn_row, text="폴더 선택", command=self.pick_folder, width=15).pack(
            side="left"
        )
        ttk.Button(btn_row, text="파일 선택", command=self.pick_files, width=15).pack(
            side="left", padx=10
        )

        self.recursive_var = tk.BooleanVar(value=False)
        self.chk_recursive = ttk.Checkbutton(
            btn_row, text="하위 폴더 포함", variable=self.recursive_var
        )
        self.chk_recursive.pack(side="left", padx=10)

        # 드래그앤드롭 영역
        self.drop_frame = ttk.Frame(main)
        self.drop_frame.pack(fill="x", pady=(0, 15))

        self.drop_label = ttk.Label(
            self.drop_frame,
            text="여기로 이미지 파일 또는 폴더를 드래그앤드롭 하세요.",
            anchor="center",
            padding=30,
            background="#ffffff",
            font=("맑은 고딕", 10, "italic"),
            foreground="#6c757d",
            relief="groove",
        )
        self.drop_label.pack(fill="x")

        # 출력 폴더 설정
        out_box = ttk.LabelFrame(main, text=" 2. 출력 설정 ", padding=15)
        out_box.pack(fill="x", pady=(0, 15))

        self.lbl_output_path = ttk.Label(
            out_box, text="기본값: [원본 폴더]/result", foreground="#495057"
        )
        self.lbl_output_path.pack(side="left", fill="x", expand=True)

        ttk.Button(out_box, text="저장 폴더 변경", command=self.pick_output_folder).pack(
            side="right"
        )

        # 선택 결과 표시
        info_box = ttk.LabelFrame(main, text=" 3. 선택 상세 내역 ", padding=15)
        info_box.pack(fill="both", expand=True, pady=(0, 15))

        self.lbl_source = ttk.Label(info_box, text="source: (미선택)", foreground="#212529")
        self.lbl_source.pack(anchor="w")

        self.lbl_count = ttk.Label(
            info_box, text="이미지 개수: 0", font=("맑은 고딕", 9, "bold"), foreground="#0d6efd"
        )
        self.lbl_count.pack(anchor="w", pady=(5, 10))

        # 리스트박스 스타일 개선
        list_frame = ttk.Frame(info_box)
        list_frame.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")

        self.listbox = tk.Listbox(
            list_frame,
            height=8,
            font=("맑은 고딕", 9),
            relief="flat",
            borderwidth=1,
            highlightthickness=1,
            highlightcolor="#0d6efd",
            background="#ffffff",
            foreground="#212529",
            selectbackground="#0d6efd",
            selectforeground="#ffffff",
            yscrollcommand=scrollbar.set,
        )
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.listbox.yview)

        # 실행 영역
        run_box = ttk.Frame(main)
        run_box.pack(fill="x", pady=(10, 0))

        self.btn_merge = ttk.Button(
            run_box, text=" PDF 생성하기 ", command=self.merge_to_pdf, style="Accent.TButton"
        )
        self.btn_merge.pack(side="left")

        self.progress = ttk.Progressbar(run_box, mode="indeterminate", length=200)
        self.progress.pack(side="left", fill="x", expand=True, padx=(15, 0))

    def _setup_dnd_if_available(self):
        """
        tkinterdnd2가 있으면 드래그앤드롭 활성화.
        없으면 안내만 제공.
        """
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD  # type: ignore
        except Exception:
            return

        # root를 TkinterDnD.Tk로 재생성해야 제대로 동작하는 환경이 많아서,
        # 여기서는 "가능하면" 활성화하는 방식으로 안내합니다.
        # 이미 Tk()로 만든 경우 일부 환경에서 제한될 수 있음.
        # (안정적으로 쓰려면 main()에서 TkinterDnD.Tk 사용)
        try:
            self.drop_label.drop_target_register(DND_FILES)
            self.drop_label.dnd_bind("<<Drop>>", self.on_drop)
            self.drop_frame.configure(text="드래그앤드롭(활성화됨)")
        except Exception:
            # 환경에 따라 제한이 있을 수 있음
            pass

    def _update_view(self):
        source_text = f"source: {self.state.source}" if self.state.source else "source: (미선택)"
        self.lbl_source.config(text=source_text)

        count = len(self.state.images or [])
        self.lbl_count.config(text=f"이미지 개수: {count}")

        self.listbox.delete(0, tk.END)
        for p in (self.state.images or []):
            self.listbox.insert(tk.END, p.name)

    def pick_folder(self):
        folder = filedialog.askdirectory(title="이미지 폴더 선택")
        if not folder:
            return
        folder_path = Path(folder)

        images = list_images_in_folder(folder_path, recursive=self.recursive_var.get())
        self.state = SelectionState(mode="folder", source=folder_path, images=images)
        self._update_view()

        if not images:
            messagebox.showwarning("주의", "선택한 폴더에서 JPG/PNG 파일을 찾지 못했습니다.")

    def pick_files(self):
        filepaths = filedialog.askopenfilenames(
            title="이미지 파일 선택",
            filetypes=[("Image Files", "*.jpg *.jpeg *.png"), ("All Files", "*.*")],
        )
        if not filepaths:
            return

        files = [Path(p) for p in filepaths if is_image(Path(p))]
        if not files:
            messagebox.showwarning("주의", "선택한 파일 중 JPG/PNG가 없습니다.")
            return

        files.sort(key=natural_key)
        src = common_parent(files)

        self.state = SelectionState(mode="files", source=src, images=files)
        self._update_view()

    def on_drop(self, event):
        """
        드롭 데이터는 플랫폼별로 형식이 다를 수 있어 최대한 보수적으로 처리.
        """
        raw = getattr(event, "data", "")
        if not raw:
            return

        # 흔한 형식: "{C:\path\file 1.png} {C:\path\file2.jpg}" 또는 "C:\path\folder"
        # 중괄호 처리
        paths: List[str] = []
        buf = ""
        in_brace = False
        for ch in raw:
            if ch == "{":
                in_brace = True
                buf = ""
            elif ch == "}":
                in_brace = False
                if buf:
                    paths.append(buf)
                    buf = ""
            elif ch.isspace() and not in_brace:
                if buf:
                    paths.append(buf)
                    buf = ""
            else:
                buf += ch
        if buf:
            paths.append(buf)

        dropped = [Path(p) for p in paths]
        # 폴더가 하나라도 있으면: 첫 폴더 기준으로 처리(명확성 우선)
        folders = [p for p in dropped if p.exists() and p.is_dir()]
        if folders:
            folder = folders[0]
            images = list_images_in_folder(folder, recursive=self.recursive_var.get())
            self.state = SelectionState(mode="folder", source=folder, images=images)
            self._update_view()
            if not images:
                messagebox.showwarning("주의", "드롭한 폴더에서 JPG/PNG 파일을 찾지 못했습니다.")
            return

        # 파일 드롭
        files = [p for p in dropped if p.exists() and is_image(p)]
        if not files:
            messagebox.showwarning("주의", "드롭한 항목에서 JPG/PNG 파일을 찾지 못했습니다.")
            return

        files.sort(key=natural_key)
        src = common_parent(files)
        self.state = SelectionState(mode="files", source=src, images=files)
        self._update_view()

    def pick_output_folder(self):
        folder = filedialog.askdirectory(title="결과물을 저장할 폴더 선택")
        if folder:
            self.custom_output_dir = Path(folder)
            self.lbl_output_path.config(text=f"저장 위치: {self.custom_output_dir}")

    def open_output_folder(self, pdf_path: Path):
        folder = pdf_path.parent
        if not folder.exists():
            messagebox.showerror("오류", "폴더가 존재하지 않습니다.")
            return

        try:
            if platform.system() == "Windows":
                os.startfile(folder)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as e:
            messagebox.showerror("오류", f"폴더 열기 실패: {e}")

    def show_success_dialog(self, pdf_path: Path):
        top = tk.Toplevel(self.root)
        top.title("생성 완료")
        top.geometry("450x220")
        top.configure(bg="#f8f9fa")
        top.resizable(False, False)

        # 팝업 내부 여백
        inner = ttk.Frame(top, padding=25)
        inner.pack(fill="both", expand=True)

        msg_lbl = ttk.Label(
            inner,
            text="PDF 생성이 완료되었습니다!",
            font=("맑은 고딕", 12, "bold"),
            foreground="#198754",
        )
        msg_lbl.pack(pady=(0, 10))

        name_lbl = ttk.Label(
            inner, text=pdf_path.name, font=("맑은 고딕", 9), foreground="#6c757d"
        )
        name_lbl.pack(pady=(0, 25))

        btn_box = ttk.Frame(inner)
        btn_box.pack(fill="x")

        ttk.Button(
            btn_box,
            text="저장 폴더 열기",
            command=lambda: [self.open_output_folder(pdf_path), top.destroy()],
        ).pack(side="left", expand=True, fill="x", padx=(0, 5))

        ttk.Button(btn_box, text="확인", command=top.destroy).pack(
            side="left", expand=True, fill="x", padx=(5, 0)
        )

    def merge_to_pdf(self):
        if not self.state.source or not self.state.images:
            messagebox.showwarning("주의", "먼저 폴더 또는 이미지 파일을 선택하세요.")
            return

        images = self.state.images
        source = self.state.source

        # 결과 경로 설정
        if self.custom_output_dir:
            out_dir = self.custom_output_dir
        else:
            out_dir = source / "result"

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_pdf = out_dir / f"merged_{ts}.pdf"

        try:
            warnings = warn_huge_images(images)
            if warnings:
                msg = (
                    "아주 큰 이미지가 포함되어 PDF 용량/렌더링이 커질 수 있습니다:\n\n"
                    + "\n".join(warnings[:10])
                )
                if len(warnings) > 10:
                    msg += f"\n... 외 {len(warnings) - 10}개"
                messagebox.showinfo("참고", msg)

            self.progress.start(12)
            self.root.update_idletasks()

            convert_images_to_pdf(images, out_pdf)

            self.progress.stop()
            self.show_success_dialog(out_pdf)
        except Exception as e:
            self.progress.stop()
            messagebox.showerror("오류", f"PDF 생성 실패:\n{e}")


def main():
    root = None
    try:
        from tkinterdnd2 import TkinterDnD  # type: ignore

        root = TkinterDnD.Tk()
    except Exception:
        root = tk.Tk()

    # 스타일 설정
    style = ttk.Style(root)

    # 기본 테마 설정 (clam이 색상 커스텀에 유리)
    if "clam" in style.theme_names():
        style.theme_use("clam")

    # 공통 색상 및 스타일 정의
    bg_color = "#f8f9fa"
    fg_color = "#212529"
    accent_color = "#0d6efd"

    style.configure(".", background=bg_color, foreground=fg_color, font=("맑은 고딕", 9))
    style.configure("TFrame", background=bg_color)
    style.configure("TLabelframe", background=bg_color, relief="solid", borderwidth=1)
    style.configure("TLabelframe.Label", background=bg_color, foreground=accent_color, font=("맑은 고딕", 10, "bold"))
    
    style.configure("TLabel", background=bg_color, foreground=fg_color)
    style.configure("TButton", padding=6)
    
    # 강조 버튼 스타일 (Accent)
    style.configure("Accent.TButton", foreground="white", background=accent_color, font=("맑은 고딕", 10, "bold"))
    style.map("Accent.TButton",
              background=[("active", "#0b5ed7"), ("pressed", "#0a58ca")],
              foreground=[("active", "white")])

    # 진행바 스타일
    style.configure("Horizontal.TProgressbar", background=accent_color, troughcolor="#e9ecef", bordercolor="#dee2e6", lightcolor=accent_color, darkcolor=accent_color)

    app = ImageToPdfApp(root)
    root.mainloop()


if __name__ == "__main__":
    raise SystemExit(main())
