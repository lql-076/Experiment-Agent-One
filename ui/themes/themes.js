/* 自动生成：Agent 启动时扫描 ui\themes 里的 .css 文件写出这份清单（直接双击 index.html 看演示时也用它）。
   不用手改：往 themes 文件夹放一个新的 .css，刷新界面就会出现在 设置 › 外观 里。 */
window.AGENT_THEMES = [{"id": "dark", "name": "极简 · 深色", "desc": "近黑的底、一点橙色。没有光斑、没有发光，字大、留白多：一眼看清现在在干什么、后台在跑什么。", "file": "dark.css", "order": 1, "v": 1793869044, "fx": ["reveal", "press"]}, {"id": "light", "name": "极简 · 浅色", "desc": "米白的底、深灰的字、一点橙色。和深色是同一套样子，白天亮的地方用。", "file": "light.css", "order": 2, "v": 1793869929, "fx": ["reveal", "press"]}];
(function () { var t = window.AGENT_THEMES; for (var i = 0; i < t.length; i++) document.write('<link rel="stylesheet" href="themes/' + t[i].file + '?v=' + t[i].v + '">'); })();
