import os
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk

class FileChooserImageApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Image Viewer (File Dialog)")
        self.geometry("800x600")
        self.configure(bg="#f7f7f7")

        # Top controls
        control_frame = tk.Frame(self, bg=self["bg"])
        control_frame.pack(pady=12)

        open_btn = tk.Button(control_frame, text="Open Image...", command=self.open_single_image)
        open_btn.grid(row=0, column=0, padx=6)

        open_multi_btn = tk.Button(control_frame, text="Open Multiple Images...", command=self.open_multiple_images)
        open_multi_btn.grid(row=0, column=1, padx=6)

        clear_btn = tk.Button(control_frame, text="Clear", command=self.clear_display)
        clear_btn.grid(row=0, column=2, padx=6)

        # Status / filename label
        self.status_label = tk.Label(self, text="No image loaded", bg=self["bg"], font=("Segoe UI", 10))
        self.status_label.pack(pady=(0, 8))

        # Canvas for single large image
        self.canvas = tk.Canvas(self, width=760, height=420, bg="white", bd=1, relief="solid")
        self.canvas.pack(padx=20, pady=10)

        # Frame for thumbnails when multiple images are opened
        thumb_container = tk.Frame(self, bg=self["bg"])
        thumb_container.pack(fill="x", pady=(6,12))
        self.thumb_frame = tk.Frame(thumb_container, bg=self["bg"])
        self.thumb_frame.pack(anchor="w", padx=10)

        # Keep references to images to avoid GC
        self.current_image_tk = None
        self.thumbnail_tks = []

        # Allowed image types for dialog
        self.filetypes = [
            ("Image files", ("*.png", "*.jpg", "*.jpeg", "*.gif", "*.bmp", "*.tiff")),
            ("All files", "*.*")
        ]

    def open_single_image(self):
        """Open a file dialog and display a single image centered on the canvas."""
        path = filedialog.askopenfilename(title="Select an image", filetypes=self.filetypes)
        if not path:
            return

        try:
            self.display_image(path)
            self.status_label.config(text=os.path.basename(path))
            self.clear_thumbnails()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open image:\n{e}")

    def open_multiple_images(self):
        """Open file dialog to select multiple images, show first in canvas and thumbnails beneath."""
        paths = filedialog.askopenfilenames(title="Select images", filetypes=self.filetypes)
        if not paths:
            return

        # Display first image in canvas
        try:
            self.display_image(paths[0])
            self.status_label.config(text=f"{len(paths)} image(s) selected — showing: {os.path.basename(paths[0])}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open image:\n{e}")
            return

        # Create thumbnails for all selected images
        self.clear_thumbnails()
        for p in paths:
            try:
                thumb = self.make_thumbnail(p, (100, 75))
                thumb_btn = tk.Button(self.thumb_frame, image=thumb, command=lambda p=p: self.on_thumbnail_click(p), bd=1)
                thumb_btn.pack(side="left", padx=6)
                # Keep reference
                self.thumbnail_tks.append(thumb)
            except Exception:
                # Skip an image that fails to load as a thumbnail
                continue

    def display_image(self, path):
        """Load, thumbnail to canvas size, and display image."""
        canvas_w = int(self.canvas["width"])
        canvas_h = int(self.canvas["height"])

        img = Image.open(path)
        img.thumbnail((canvas_w - 4, canvas_h - 4), Image.Resampling.LANCZOS)
        self.current_image_tk = ImageTk.PhotoImage(img)

        self.canvas.delete("all")
        # center
        x = canvas_w // 2
        y = canvas_h // 2
        self.canvas.create_image(x, y, image=self.current_image_tk)
        self.canvas.update()

    def make_thumbnail(self, path, size=(100, 75)):
        """Create and return a tkinter PhotoImage thumbnail (keeps reference for GC)."""
        img = Image.open(path)
        img.thumbnail(size, Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(img)

    def on_thumbnail_click(self, path):
        """When a thumbnail is clicked, show that image in the main canvas."""
        try:
            self.display_image(path)
            self.status_label.config(text=os.path.basename(path))
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open image:\n{e}")

    def clear_thumbnails(self):
        """Remove thumbnail widgets and references."""
        for widget in self.thumb_frame.winfo_children():
            widget.destroy()
        self.thumbnail_tks.clear()

    def clear_display(self):
        """Clear canvas, thumbnails, and status."""
        self.canvas.delete("all")
        self.clear_thumbnails()
        self.status_label.config(text="No image loaded")
        self.current_image_tk = None


if __name__ == "__main__":
    app = FileChooserImageApp()
    app.mainloop()
