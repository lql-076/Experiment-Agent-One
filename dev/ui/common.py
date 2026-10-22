"""专项界面测试共用：启动浏览器。沙箱里 playwright 版本和自带的 Chromium 对不上时，直接用自带的。"""


def launch(pw):
    try:
        return pw.chromium.launch()
    except Exception:
        return pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
