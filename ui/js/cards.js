'use strict';
/* ================= 提醒卡片（界面上挂着，直到你确认） ================= */
var cardSig = '', cardMin = {};
/* 样本攒够了，问你要不要训练（QQ 上也问了，哪边回都行） */
function trainCardHTML(ta) {
  if (!ta) return '';
  if (cardMin.train) return '<button class="rpill" data-card-open="train">🧠 要不要训练「' + esc(ta.cat) + '」？</button>';
  return '<div class="rcard tcard"><div class="rc-t">🧠 要不要训练「' + esc(ta.cat) + '」？</div><div class="rc-x">这类事的样本攒够了（' + (ta.n || '') + ' 条），可以训练一个新小脑。训练时显卡会被占满一阵子，玩游戏时别开。</div>' +
    '<div class="rc-m">' + (ta.times > 1 ? '第 ' + ta.times + ' 次问 · ' : '') + 'QQ 上回「开始」或「等一下」也行；不回的话隔 ' + (S.set.trainAsk || 2) + ' 小时再问</div>' +
    '<div class="btnrow"><button class="btn primary" data-train-go>开始训练</button><button class="btn" data-train-wait>等一下</button><button class="btn" data-card-min style="margin-left:auto">收起</button></div></div>';
}
function renderCards(cards) {
  cards = useLive() ? (cards || []) : [];
  var ta = useLive() && D.state ? D.state.train_ask : null;
  var sig = cards.map(function (c) { return c.id + (cardMin[c.id] ? 'm' : ''); }).join(',') + '|' + (ta ? ta.cat + ta.times + (cardMin.train ? 'm' : '') : '');
  if (sig === cardSig) return; cardSig = sig;
  if (!cards.length) { $('#cards').innerHTML = trainCardHTML(ta); return; }
  var c = cards[cards.length - 1], rest = cards.slice(0, -1), d = new Date(c.ts * 1000);
  if (cardMin[c.id]) { $('#cards').innerHTML = trainCardHTML(ta) + '<button class="rpill" data-card-open="' + c.id + '">⏰ ' + esc(c.title) + ' · 还没确认' + (rest.length ? '（共 ' + cards.length + ' 条）' : '') + '</button>'; return; }
  $('#cards').innerHTML = trainCardHTML(ta) + '<div class="rcard" data-did="' + c.id + '"><div class="rc-t">⏰ ' + esc(c.title) + '</div>' + (c.text ? '<div class="rc-x">' + esc(c.text) + '</div>' : '') +
    '<div class="rc-m">' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ' 发出 · QQ 和这里都会提醒，点一下就算确认</div><div class="btnrow"><button class="btn primary" data-card-ack>好了</button><button class="btn" data-card-snooze>晚点 30 分钟</button><button class="btn" data-card-min style="margin-left:auto">收起</button></div>' +
    (rest.length ? '<div class="rc-more"><span>另外还有 ' + rest.length + ' 条没确认（' + esc(rest.map(function (x) { return x.title; }).slice(-3).join('、')) + '）</span><button class="linkbtn" data-card-all="' + rest.map(function (x) { return x.id; }).join(',') + '">全部好了</button></div>' : '') + '</div>';
}
$('#cards').addEventListener('click', function (ev) {
  ev.stopPropagation();
  var t = ev.target.closest('button'); if (!t) return;
  if (t.dataset.cardOpen) { delete cardMin[t.dataset.cardOpen]; cardSig = ''; renderCards(D.state && D.state.cards); return; }
  if (t.hasAttribute('data-train-go') || t.hasAttribute('data-train-wait')) {
    var go = t.hasAttribute('data-train-go'); t.disabled = true;
    api('POST', '/api/train/answer', { go: go }).then(function (j) { toast(j.msg, 6000); if (D.state) D.state.train_ask = null; cardSig = ''; renderCards(D.state && D.state.cards); poll(); }).catch(function (e) { t.disabled = false; toast(e.message); });
    return;
  }
  var card = ev.target.closest('.rcard'); if (!card) return;
  if (card.classList.contains('tcard') && t.hasAttribute('data-card-min')) { cardMin.train = 1; cardSig = ''; renderCards(D.state && D.state.cards); return; }
  if (t.hasAttribute('data-card-min')) { cardMin[card.dataset.did] = 1; cardSig = ''; renderCards(D.state && D.state.cards); return; }
  if (t.dataset.cardAll) { Promise.all(t.dataset.cardAll.split(',').map(function (x) { return api('POST', '/api/deliveries/' + x + '/ack', {}); })).then(function () { cardSig = ''; poll(); toast('都确认了'); }); return; }
  var id = card.dataset.did, path = t.hasAttribute('data-card-ack') ? '/ack' : '/snooze';
  api('POST', '/api/deliveries/' + id + path, { minutes: 30 }).then(function () { card.remove(); cardSig = ''; toast(path === '/ack' ? '已打卡' : '30 分钟后再提醒'); poll(); }).catch(function (e) { toast(e.message); });
});
$('#cards').addEventListener('pointerdown', function (ev) { ev.stopPropagation(); });
