"""! @brief Touch-operated Wi-Fi selection using the system NetworkManager."""

import subprocess
import threading

from PIL import Image, ImageDraw


def _fields(line):
    """! @brief Decode one escaped, colon-separated nmcli output line.
    @param line Line produced by nmcli with terse escaping enabled.
    @return Decoded column values.
    """
    values, value, escaped = [], "", False
    for character in line:
        if escaped:
            value += character
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == ":":
            values.append(value)
            value = ""
        else:
            value += character
    values.append(value + ("\\" if escaped else ""))
    return values


def _nmcli(*args, input_text=None, timeout=12):
    """! @brief Run nmcli without a shell, keeping credentials out of arguments.
    @param args Command arguments following nmcli.
    @param input_text Optional secret supplied through standard input.
    @param timeout Maximum execution time in seconds.
    @return Completed subprocess result.
    """
    return subprocess.run(["nmcli", *args], input=input_text, capture_output=True,
                          text=True, timeout=timeout)


def scan_networks():
    """! @brief List visible networks and match saved Wi-Fi profiles.
    @return List of network dictionaries, with the strongest duplicate first.
    @exception OSError If NetworkManager cannot list available networks.
    """
    result = _nmcli("-t", "-e", "yes", "-f", "IN-USE,SSID,SIGNAL,SECURITY",
                    "device", "wifi", "list", "--rescan", "yes", "ifname", "wlan0", timeout=20)
    if result.returncode:
        raise OSError("无法扫描 Wi-Fi")
    networks = {}
    for line in result.stdout.splitlines():
        columns = _fields(line)
        if len(columns) != 4:
            continue
        active, ssid, signal, security = columns
        if not ssid or any(ord(character) < 32 for character in ssid):
            continue
        try:
            signal = int(signal)
        except ValueError:
            continue
        entry = {"ssid": ssid, "signal": signal, "security": security,
                 "active": active == "*", "uuid": None}
        old = networks.get(ssid)
        if old is None or entry["active"] or (not old["active"] and signal > old["signal"]):
            networks[ssid] = entry
    profiles = _nmcli("-t", "-e", "yes", "-f", "UUID,TYPE", "connection", "show")
    if profiles.returncode == 0:
        for line in profiles.stdout.splitlines():
            columns = _fields(line)
            if len(columns) != 2 or columns[1] not in ("802-11-wireless", "wifi"):
                continue
            profile = _nmcli("-g", "802-11-wireless.ssid", "connection", "show",
                             "uuid", columns[0])
            ssid = _fields(profile.stdout.rstrip("\n"))[0]
            if profile.returncode == 0 and ssid in networks:
                networks[ssid]["uuid"] = columns[0]
    return sorted(networks.values(), key=lambda item: (not item["active"], -item["signal"]))


def connect_network(network, password=None):
    """! @brief Connect a saved, open or password-protected network.
    @param network Network selected from scan_networks().
    @param password New WPA password, or None to use a saved profile.
    @return True when NetworkManager reports successful activation.
    """
    previous = _nmcli("-g", "GENERAL.CON-UUID", "device", "show", "wlan0")
    previous_uuid = previous.stdout.strip() if previous.returncode == 0 else ""
    try:
        if password is None and network["uuid"]:
            result = _nmcli("-w", "25", "connection", "up", "uuid", network["uuid"],
                            "ifname", "wlan0", timeout=30)
        else:
            args = ["-w", "25"]
            if password is not None:
                args.append("--ask")
            args.extend(("device", "wifi", "connect", network["ssid"], "ifname", "wlan0"))
            result = _nmcli(*args, input_text=None if password is None else password + "\n", timeout=30)
        connected = result.returncode == 0
    except subprocess.SubprocessError:
        connected = False
    if not connected and previous_uuid and previous_uuid != "--":
        try:
            _nmcli("-w", "15", "connection", "up", "uuid", previous_uuid,
                   "ifname", "wlan0", timeout=20)
        except (OSError, subprocess.SubprocessError):
            pass
    return connected


class WifiPanel:
    """! @brief Draw a Wi-Fi list and password keyboard on the rotating touch display."""

    LETTERS = ("1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm")
    SYMBOLS = ("!@#$%^&*()", "-_=+[]{};:", "\\|,<.>/?'\"", "`~")
    CONTROLS = ("大小写", "符号", "空格", "删除", "连接", "返回")

    def __init__(self, screen):
        """! @brief Initialize the panel using the existing display and font.
        @param screen AI Box screen object.
        """
        self.screen = screen
        self.lock = threading.Lock()
        self.active = False
        self.mode = "list"
        self.networks = []
        self.page = 0
        self.message = ""
        self.selected = None
        self.password = ""
        self.upper = False
        self.symbols = False
        self.generation = 0
        self.small_font = screen.font.font_variant(size=22)

    def open(self):
        """! @brief Open the panel and refresh nearby Wi-Fi networks."""
        with self.lock:
            self.active = True
            self.networks = []
            self.page = 0
            self._scan_locked()

    def _scan_locked(self):
        """! @brief Start a scan without blocking the touch interface."""
        self.mode = "list"
        self.message = "正在扫描…"
        self.generation += 1
        generation = self.generation
        self._draw_locked()
        threading.Thread(target=self._scan, args=(generation,), daemon=True).start()

    def _scan(self, generation):
        """! @brief Complete a scan if its panel is still current.
        @param generation Scan generation used to discard stale results.
        """
        try:
            networks = scan_networks()
            message = "请选择网络" if networks else "未找到网络，请刷新"
        except (OSError, subprocess.SubprocessError):
            networks, message = [], "扫描失败，请重试"
        with self.lock:
            if not self.active or generation != self.generation or self.mode != "list":
                return
            self.networks = networks
            self.page = min(self.page, max(0, (len(networks) - 1) // 5))
            self.message = message
            self._draw_locked()

    def _start_connect_locked(self, network, password=None):
        """! @brief Connect in a worker so that drawing never waits for Wi-Fi.
        @param network Selected network.
        @param password New password, or None for a saved/open network.
        """
        self.mode = "busy"
        self.generation += 1
        self.message = "正在连接，请稍候…"
        self.password = ""
        self._draw_locked()
        threading.Thread(target=self._connect, args=(network, password), daemon=True).start()

    def _connect(self, network, password):
        """! @brief Complete a connection and display its result.
        @param network Selected network.
        @param password New password, or None for a saved/open network.
        """
        try:
            result = connect_network(network, password)
        except (OSError, subprocess.SubprocessError):
            result = False
        with self.lock:
            if not self.active:
                return
            if result:
                self._scan_locked()
            elif network["security"] != "--":
                self.mode = "password"
                self.message = "连接失败，请检查密码"
                self._draw_locked()
            else:
                self.mode = "list"
                self.message = "连接失败，请重试"
                self._draw_locked()

    def touch(self, x, y):
        """! @brief Handle one touch in display coordinates.
        @param x Horizontal coordinate after applying screen rotation.
        @param y Vertical coordinate after applying screen rotation.
        @return True when the panel was closed.
        """
        with self.lock:
            width, height = self.screen.display.width, self.screen.display.height
            if self.mode == "busy":
                return False
            if self.mode == "list":
                if y < 60:
                    action = min(3, x * 4 // width)
                    if action == 0:
                        self.active = False
                        self.generation += 1
                        return True
                    if action == 1:
                        self._scan_locked()
                        return False
                    self.page = max(0, min(max(0, (len(self.networks) - 1) // 5),
                                           self.page + (-1 if action == 2 else 1)))
                elif y < height - 50:
                    index = self.page * 5 + (y - 60) * 5 // (height - 110)
                    if index < len(self.networks):
                        self.selected = self.networks[index]
                        network = self.selected
                        security = network["security"].upper()
                        if network["active"]:
                            self.message = "此网络已连接"
                        elif "802.1X" in security or "WEP" in security or (
                                "WPA3" in security and "WPA2" not in security):
                            self.message = "暂不支持此网络的加密方式"
                        elif network["uuid"] or security == "--":
                            self._start_connect_locked(network)
                            return False
                        else:
                            self.password = ""
                            self.mode = "password"
                            self.message = "请输入 Wi-Fi 密码"
                self._draw_locked()
                return False
            if y >= height - 60:
                action = min(5, x * 6 // width)
                if action == 0:
                    self.upper = not self.upper
                elif action == 1:
                    self.symbols = not self.symbols
                elif action == 2:
                    self.password += " " if len(self.password) < 64 else ""
                elif action == 3:
                    self.password = self.password[:-1]
                elif action == 4:
                    valid = 8 <= len(self.password) <= 63 or (
                        len(self.password) == 64 and all(c in "0123456789abcdefABCDEF" for c in self.password))
                    if valid:
                        self._start_connect_locked(self.selected, self.password)
                        return False
                    self.message = "密码须为 8 到 63 位"
                else:
                    self.password = ""
                    self.mode = "list"
                    self.message = "请选择网络"
            elif 100 <= y < height - 60:
                rows = self.SYMBOLS if self.symbols else self.LETTERS
                row = min(3, (y - 100) * 4 // (height - 160))
                keys = rows[row].upper() if self.upper and not self.symbols else rows[row]
                column = min(len(keys) - 1, x * len(keys) // width)
                if len(self.password) < 64:
                    self.password += keys[column]
            self._draw_locked()
            return False

    def _draw_locked(self):
        """! @brief Draw the current panel state without exposing the password."""
        width, height = self.screen.display.width, self.screen.display.height
        image = Image.new("RGB", (width, height), "black")
        draw = ImageDraw.Draw(image)
        font, small = self.screen.font, self.small_font

        def label(box, text, selected=False, text_font=None):
            text_font = text_font or small
            draw.rectangle(box, outline="white", fill="#24405a" if selected else "#151515", width=1)
            left, top, right, bottom = draw.textbbox((0, 0), text, font=text_font)
            draw.text(((box[0] + box[2] - (right - left)) / 2 - left,
                       (box[1] + box[3] - (bottom - top)) / 2 - top),
                      text, font=text_font, fill="white")

        if self.mode in ("list", "busy"):
            for index, title in enumerate(("返回", "刷新", "上一页", "下一页")):
                label((index * width // 4, 0, (index + 1) * width // 4 - 1, 55), title)
            row_height = height - 110
            for row, network in enumerate(self.networks[self.page * 5:self.page * 5 + 5]):
                top = 60 + row * row_height // 5
                bottom = 60 + (row + 1) * row_height // 5 - 1
                suffix = "  {}%{}".format(network["signal"], " 已连接" if network["active"] else "")
                name = network["ssid"]
                while name and draw.textbbox((0, 0), name + suffix, font=font)[2] > width - 20:
                    name = name[:-1]
                label((0, top, width - 1, bottom), name + suffix, network["active"], font)
            draw.text((8, height - 43), self.message, font=small, fill="yellow")
        else:
            title = "连接 " + self.selected["ssid"]
            while title and draw.textbbox((0, 0), title, font=small)[2] > width - 16:
                title = title[:-1]
            draw.text((8, 2), title, font=small, fill="white")
            draw.text((8, 30), self.message, font=small, fill="yellow")
            draw.text((8, 60), "*" * min(len(self.password), 32), font=small, fill="white")
            rows = self.SYMBOLS if self.symbols else self.LETTERS
            for row, keys in enumerate(rows):
                keys = keys.upper() if self.upper and not self.symbols else keys
                top = 100 + row * (height - 160) // 4
                bottom = 100 + (row + 1) * (height - 160) // 4 - 1
                for column, key in enumerate(keys):
                    label((column * width // len(keys), top,
                           (column + 1) * width // len(keys) - 1, bottom), key, text_font=font)
            for index, title in enumerate(self.CONTROLS):
                label((index * width // 6, height - 58, (index + 1) * width // 6 - 1, height - 1), title)
        self.screen.display.display(image)
