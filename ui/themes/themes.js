/* 自动生成：Agent 启动时扫描 ui\themes 里的 .css 文件写出这份清单（直接双击 index.html 看演示时也用它）。
   不用手改：往 themes 文件夹放一个新的 .css，刷新界面就会出现在 设置 › 外观 里。 */
window.AGENT_THEMES = [{"id": "dark", "name": "指挥舱 · 夜航", "desc": "近黑的深蓝底、青色的线、干活时变琥珀色。切角面板、中间一颗会动的核心：一眼看清现在在干什么、做到计划的第几步。", "file": "dark.css", "order": 1, "v": 1794383325, "fx": ["reveal", "press"]}, {"id": "light", "name": "指挥舱 · 日间", "desc": "冷白的底、深蓝灰的字、青蓝的线。和夜航是同一套样子，白天亮的地方用（不发光、没有扫描线）。", "file": "light.css", "order": 2, "v": 1794383325, "fx": ["reveal", "press"]}];
(function () { var t = window.AGENT_THEMES; for (var i = 0; i < t.length; i++) document.write('<link rel="stylesheet" href="themes/' + t[i].file + '?v=' + t[i].v + '">'); })();
