"""! @brief Full-screen AI Box interface for the Taishanpi MIPI touch display."""

from contextlib import ExitStack
from pathlib import Path
from queue import Empty, Full, Queue
import threading
import tkinter as tk

from PIL import Image, ImageTk

from .app import Application
from .ui import Screen, load_font, menu_index_at
from .wifi import WifiPanel


ORIENTATION_PATH = Path("/var/lib/ai-box/orientation")


class TouchDisplay:
    """! @brief Present application frames in the desktop session's main thread."""

    def __init__(self, root):
        """! @brief Create a full-screen window and a latest-frame queue.
        @param root Tk root owned by the calling thread.
        """
        self.root = root
        self.physical_width = root.winfo_screenwidth()
        self.physical_height = root.winfo_screenheight()
        try:
            saved = ORIENTATION_PATH.read_text().strip()
            self.orientation = {"portrait": 0, "landscape": 90, "0": 0, "90": 90,
                                "180": 180, "270": 270}.get(saved, 0)  # 旋转角度
        except FileNotFoundError:
            self.orientation = 0
        self._set_size()  # 根据旋转角度设置实际的宽高
        self.frames = Queue(maxsize=1)
        self.label = tk.Label(root, background="black", borderwidth=0)
        self.label.pack(fill="both", expand=True)
        root.attributes("-fullscreen", True)
        self.image = None

    def _set_size(self):
        """! @brief Match the drawing size to the selected orientation."""
        if self.orientation in (90, 270):
            self.width, self.height = self.physical_height, self.physical_width
        else:
            self.width, self.height = self.physical_width, self.physical_height

    def rotate(self):
        """! @brief Switch orientation, save it, and discard old-sized frames."""
        orientation = (self.orientation + 90) % 360
        ORIENTATION_PATH.parent.mkdir(parents=True, exist_ok=True)
        ORIENTATION_PATH.write_text("{}\n".format(orientation))
        self.orientation = orientation
        self._set_size()
        try:
            self.frames.get_nowait()
        except Empty:
            pass

    def touch_x(self, event):
        """! @brief Convert a physical touch to the drawing's horizontal axis.
        @param event Tk pointer event on the physical screen.
        @return Horizontal coordinate in the selected orientation.
        """
        return self.touch_point(event)[0]

    def touch_point(self, event):
        """! @brief Map a physical touch to both rotated drawing coordinates.
        @param event Tk pointer event on the physical screen.
        @return Pair of horizontal and vertical coordinates.
        """
        if self.orientation == 90:
            return self.physical_height - 1 - event.y, event.x
        if self.orientation == 180:
            return self.physical_width - 1 - event.x, self.physical_height - 1 - event.y
        if self.orientation == 270:
            return event.y, self.physical_width - 1 - event.x
        return event.x, event.y

    def display(self, frame):
        """! @brief Queue a frame safely from the menu or voice worker.
        @param frame Pillow image sized to this display.
        """
        while True:
            try:
                self.frames.put_nowait(frame)
                return
            except Full:
                try:
                    self.frames.get_nowait()
                except Empty:
                    pass

    def refresh(self):
        """! @brief Show the latest queued frame from the Tk thread."""
        try:
            frame = self.frames.get_nowait()
        except Empty:
            return
        if self.orientation:
            rotations = getattr(Image, "Transpose", Image)
            frame = frame.transpose(getattr(rotations, "ROTATE_{}".format(self.orientation)))
        self.image = ImageTk.PhotoImage(frame, master=self.root)
        self.label.configure(image=self.image)


def main(voice_only=False):
    """! @brief Run the app launcher with direct touch selection.
    @param voice_only Start the voice assistant immediately.
    """
    root = tk.Tk()
    with ExitStack() as cleanup:
        cleanup.callback(root.destroy)
        display = TouchDisplay(root)
        screen = Screen(display, load_font())
        network = WifiPanel(screen)
        app = Application(screen, rotate=display.rotate, network=network)
        if voice_only:
            app.select(0)
        errors = Queue()

        def run_app():
            try:
                app.run()
            except Exception as error:
                errors.put(error)

        worker = threading.Thread(target=run_app)  # 创建一个线程对象，并指定此对象启动后执行run_app()
        worker.start() # 启动线程，让 run_app() 在后台执行
        cleanup.callback(worker.join) # 这里不是立即等待线程结束，而是把 worker.join 登记为退出时要执行的清理操作。
        cleanup.callback(app.close) # 同样是登记清理操作。退出时调用 app.close()

        def touch(event):
            x, y = display.touch_point(event)
            if network.active:
                if network.touch(x, y):
                    app.refresh_menu()
                return
            index = menu_index_at(display.width, display.height, len(app.main_menu), x, y)
            app.select(index)

        def refresh():
            display.refresh()
            if not worker.is_alive():
                root.quit()
                return
            root.after(30, refresh)

        root.bind("<Button-1>", touch)  # 当 Tk 收到鼠标左键点击事件时，调用前面定义的 touch(event) 函数
        root.bind("<Escape>", lambda event: root.quit()) # 按键盘上的 Esc 时，调用 root.quit()，让 Tk 的事件循环退出。
        root.protocol("WM_DELETE_WINDOW", root.quit)
        root.after(0, refresh)
        root.mainloop()
        if not errors.empty():
            raise errors.get()
