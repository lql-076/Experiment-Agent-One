"""开机自启（设置 › 自动化 的开关，app/autostart.py）。碰 Windows 的那几个小函数换成假的：
1. 开：写当前用户的启动项，命令是 pythonw + launch.py --autostart（不要管理员）
2. bat 建的旧任务在：开关显示开着，不再多写一条；关掉时删旧任务（要管理员确认，点「否」时说清楚）
3. 启动项指向别的文件夹（旧的 Agent）：不算开着，打开时改成现在这个
4. launch.py --autostart：依赖清单没变就自己起；变了交给 启动.bat 去补装
用法：python dev/test_autostart.py"""
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import autostart as A, launch, paths  # noqa: E402

bad = []


def check(ok, msg):
    print(("  ✓ " if ok else "  ✗ ") + msg, flush=True)
    if not ok:
        bad.append(msg)


REG, TASK, ASKED = {"v": None}, {"v": False}, []
A._reg_get = lambda: REG["v"]
A._reg_set = lambda v: REG.update(v=v)
A._reg_del = lambda: REG.update(v=None)
A._task_exists = lambda: TASK["v"]


def task_delete(ok):
    def f():
        ASKED.append(1)
        if ok:
            TASK["v"] = False
        return ok
    return f


paths.IS_WIN = True
check(A.state()["on"] is False, "什么都没有：关着")
r = A.switch(True)
check(r["on"] and r["run"] and "launch.py" in REG["v"] and "--autostart" in REG["v"] and "pythonw" in REG["v"], f"打开：写进启动项（{REG['v'][-60:]}）")
check("不要管理员" in r["msg"], "打开不要管理员：" + r["msg"])
r = A.switch(False)
check(not r["on"] and REG["v"] is None and not ASKED, "关掉：启动项删了；没有旧任务就不弹管理员确认")
TASK["v"] = True
r = A.state()
check(r["on"] and r["task"] and not r["run"], "「开机自启.bat」建的旧任务在：开关显示开着")
r = A.switch(True)
check(REG["v"] is None and "开机自启.bat" in r["msg"], "旧任务在时再点打开：不多写一条（免得开两次）")
A._task_delete = task_delete(False)
r = A.switch(False)
check(ASKED and r["on"] and "点了「否」" in r["msg"], "关掉时管理员确认点了「否」：说清楚旧任务还在")
A._task_delete = task_delete(True)
r = A.switch(False)
check(not r["on"] and not TASK["v"] and "旧任务也删了" in r["msg"], "再关一次点「是」：旧任务删了")
REG["v"] = r'"D:\旧的Agent\.venv\Scripts\pythonw.exe" "D:\旧的Agent\app\launch.py" --autostart'
r = A.state()
check(not r["on"] and r["other"], "启动项指向别的文件夹：不算开着，界面上提一句")
A.switch(True)
check(str(paths.ROOT) in REG["v"], "打开：改成现在这个文件夹")
paths.IS_WIN = False
check(A.state()["ok"] is False, "不是 Windows：开关灰着")

# launch.py --autostart
tmp = pathlib.Path(tempfile.mkdtemp())
(tmp / ".venv").mkdir()
(tmp / "requirements.txt").write_text("fastapi\n")
opened = []
launch.ROOT = tmp
launch.os.startfile = lambda p: opened.append(p)
(tmp / ".venv" / "requirements.done").write_text("fastapi\n")
check(launch.autostart() is False and not opened, "依赖清单没变：自己起（不开黑窗口）")
(tmp / "requirements.txt").write_text("fastapi\nnewdep\n")
check(launch.autostart() is True and opened and opened[-1].endswith("启动.bat"), "依赖清单变了（刚更新了版本）：交给 启动.bat 去补装")

print("不过的：", bad or "没有")
sys.exit(1 if bad else 0)
