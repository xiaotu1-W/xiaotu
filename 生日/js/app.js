/* ============================================================
 * 生日纪念页面 · 交互脚本（原生 JS，无任何依赖）· 第二版
 * ------------------------------------------------------------
 * 第二版结构：首页封面 + 入口卡片 + 弹窗面板（不再是长滚动整页）
 *
 * 模块一览：
 *   1. DATA       读取 config.js 的配置（带兜底）
 *   2. utils      小工具：取元素、转义文本、随机数
 *   3. icons      线条图标：Hello Kitty / 蝴蝶结 / 小星星 / 入口图标
 *   4. hydrate    把配置里的文字写进页面（封面、书信、彩蛋）
 *   5. floaters   首页缓慢漂浮的蝴蝶结、小星星、小圆点
 *   6. reveal     元素进入视口时淡入（弹窗内重新触发）
 *   7. entries    生成入口卡片
 *   8. gallery    照片仓库：分批渲染拍立得 + 全屏大图预览
 *   9. notes      碎碎念便签
 *  10. sheets     弹窗开关（焦点管理、Esc、锁定背景滚动、下滑关闭）
 *  11. music      右下角背景音乐按钮（绝不自动播放）
 *  12. ending     打开彩蛋弹窗时，线条蛋糕升起 + 星光散开
 *  13. boot       加载过渡 + 统一初始化
 *
 * 设计原则：
 *   - 持续动画只用 opacity / transform，60fps 无压力
 *   - 尊重系统的「减少动态效果」偏好
 *   - 所有文字走 textContent / 转义，避免特殊字符破坏页面
 * ============================================================ */
(() => {
  'use strict';

  /* ------------------------------------------------------------
   * 1. DATA：读取 config.js
   *    如果 config.js 被误删或写法有误，使用内置兜底数据，
   *    保证页面永远能正常打开（不会白屏）。
   * ------------------------------------------------------------ */
  const FALLBACK = {
    cover: {
      eyebrow: 'for my dearest',
      titleChars: ['生', '日', '快', '乐'],
      subtitle: '把这些小小的开心，都装进粉粉的盒子里',
      nfc: '轻触 NFC 卡片，与你奔赴这一份专属温柔'
    },
    entries: {
      order: ['gallery', 'letter', 'notes', 'ending'],
      gallery: { name: '照片仓库', desc: '' },
      letter: { name: '一封信', desc: '' },
      notes: { name: '碎碎念', desc: '' },
      ending: { name: '拆彩蛋', desc: '' }
    },
    letter: { title: '写给你的一封信', to: '致 你', name: '你', paragraphs: ['见字如面。'], date: '', sign: '' },
    photos: [{ src: 'images/photo-01.jpg', note: '' }],
    notes: { title: '碎碎念', items: [{ text: '愿你所愿皆成真。' }] },
    ending: { title: '拆开看看', wish: '', from: '', to: '' },
    music: { tracks: [], volume: 0.35 }
  };

  const raw = window.BIRTHDAY_DATA;
  if (!raw) {
    console.warn('[生日页面] 没有读到 config.js，已使用内置兜底内容。');
  }
  const DATA = {
    cover: { ...FALLBACK.cover, ...(raw && raw.cover) },
    entries: { ...FALLBACK.entries, ...(raw && raw.entries) },
    letter: { ...FALLBACK.letter, ...(raw && raw.letter) },
    photos: (raw && Array.isArray(raw.photos) && raw.photos.length) ? raw.photos : FALLBACK.photos,
    notes: { ...FALLBACK.notes, ...(raw && raw.notes) },
    ending: { ...FALLBACK.ending, ...(raw && raw.ending) },
    music: { ...FALLBACK.music, ...(raw && raw.music) },
    galleryBatch: Math.max(4, Number(raw && raw.galleryBatch) || 12),
    placeholderTint: (raw && raw.placeholderTint) || '#fde6ec'
  };

  /* 只保留下有 src 的照片，后续所有逻辑都用这份干净的数据 */
  const PHOTOS = (Array.isArray(DATA.photos) ? DATA.photos : []).filter((p) => p && p.src);

  /* ------------------------------------------------------------
   * 2. utils
   * ------------------------------------------------------------ */
  const $ = (sel, root = document) => root.querySelector(sel);

  const reduceMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
  const prefersReducedMotion = () => reduceMotionQuery.matches;
  const isDark = () => window.matchMedia('(prefers-color-scheme: dark)').matches;

  /** 文本一律走 textContent / 转义，避免特殊字符破坏页面 */
  const esc = (str) => String(str ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  const rand = (min, max) => min + Math.random() * (max - min);

  /* ------------------------------------------------------------
   * 3. icons：所有线条小图标都内联在这里（零图片请求、可随主题变色）
   * ------------------------------------------------------------ */

  /** 线条 Hello Kitty（脑袋轮廓 + 蝴蝶结 + 胡须），颜色随 currentColor 变化 */
  function kittySVG() {
    return `
      <path class="kitty-head" d="M28 40c-8-6-14-14-9-22 4-6 13-3 17 4 6-3 12-4 18-4h4c6 0 12 1 18 4 4-7 13-10 17-4 5 8-1 16-9 22-2 16-16 28-38 28S30 56 28 40z" />
      <g class="kitty-line">
        <ellipse cx="47" cy="44" rx="2.6" ry="3.4" />
        <ellipse cx="73" cy="44" rx="2.6" ry="3.4" />
        <ellipse cx="60" cy="51" rx="3.6" ry="2.6" />
        <path d="M31 46l-9 5M31 51l-8 9M89 46l9 5M89 51l8 9" />
      </g>
      <g class="kitty-bow">
        <ellipse cx="92" cy="27" rx="9" ry="6.5" transform="rotate(-22 92 27)" />
        <ellipse cx="108" cy="27" rx="9" ry="6.5" transform="rotate(22 108 27)" />
        <circle cx="100" cy="27" r="3.2" />
      </g>`;
  }

  /** 封面用的 Kitty 头像：脸是奶白色填充，蝴蝶结带粉边（更有存在感） */
  const KITTY_HEAD = `
    <path class="kitty-fill" d="M28 40c-8-6-14-14-9-22 4-6 13-3 17 4 6-3 12-4 18-4h4c6 0 12 1 18 4 4-7 13-10 17-4 5 8-1 16-9 22-2 16-16 28-38 28S30 56 28 40z" />
    <path class="kitty-line" d="M31 46l-9 5M31 51l-8 9M89 46l9 5M89 51l8 9" />
    <ellipse class="kitty-line" cx="47" cy="44" rx="2.6" ry="3.4" />
    <ellipse class="kitty-line" cx="73" cy="44" rx="2.6" ry="3.4" />
    <ellipse class="kitty-line" cx="60" cy="51" rx="3.6" ry="2.6" />
    <g class="kitty-bow">
      <ellipse cx="92" cy="27" rx="9" ry="6.5" transform="rotate(-22 92 27)" />
      <ellipse cx="108" cy="27" rx="9" ry="6.5" transform="rotate(22 108 27)" />
      <circle cx="100" cy="27" r="3.2" />
    </g>`;

  /** 线条蝴蝶结（漂浮用） */
  const BOW_SVG = `
    <ellipse class="bow-fill" cx="11" cy="15" rx="9.5" ry="7" transform="rotate(-18 11 15)" />
    <ellipse class="bow-fill" cx="29" cy="15" rx="9.5" ry="7" transform="rotate(18 29 15)" />
    <circle cx="20" cy="15" r="3.4" fill="currentColor" opacity=".55" />`;

  /** 四芒星（线条） */
  const STAR_SVG = `
    <path d="M12 3c.6 5 3.6 8 8.6 8.6C15.6 12.2 12.6 15.2 12 20.6c-.6-5.4-3.6-8.4-8.6-9C8.4 11 11.4 8 12 3z"
          fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" />`;

  /** 入口卡片图标 */
  const ENTRY_ICONS = {
    gallery: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <rect x="3" y="5" width="18" height="14" rx="2.5" /><circle cx="9" cy="10" r="1.8" /><path d="M4 17l5-4.5 3.5 3 3-2.5L20 17" /></svg>`,
    letter: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <rect x="3" y="5.5" width="18" height="13" rx="2.5" /><path d="M3.8 7l8.2 6 8.2-6" /></svg>`,
    notes: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M5 4.5h14a1.5 1.5 0 0 1 1.5 1.5v9.5a1.5 1.5 0 0 1-1.5 1.5h-6l-4.5 3.5V17H5a1.5 1.5 0 0 1-1.5-1.5V6A1.5 1.5 0 0 1 5 4.5z" />
      <path d="M8 9h8M8 12.2h5" /></svg>`,
    ending: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M4 9.5h16v9.5a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 19V9.5z" />
      <path d="M3 6.5h18v3H3z" />
      <path d="M12 6.5V20.5" />
      <path d="M12 6.5c-1.5-3.2-6-3.6-6-1s4 1.6 6 1zM12 6.5c1.5-3.2 6-3.6 6-1s-4 1.6-6 1z" /></svg>`
  };

  /** 入口卡片右侧的小箭头 */
  const ARROW_ICON = `<svg class="entry-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6" /></svg>`;

  /* ------------------------------------------------------------
   * 4. hydrate：把配置文字写进页面
   * ------------------------------------------------------------ */
  function hydrate() {
    // ---- 封面 ----
    const chars = Array.isArray(DATA.cover.titleChars) && DATA.cover.titleChars.length
      ? DATA.cover.titleChars
      : FALLBACK.cover.titleChars;

    const titleEl = $('#homeTitle');
    titleEl.innerHTML = chars.map((ch, i) =>
      `<span style="--d:${260 + i * 180}ms">${esc(ch)}</span>`
    ).join('');
    titleEl.setAttribute('aria-label', chars.join(''));

    $('#coverEyebrow').textContent = DATA.cover.eyebrow || '';
    $('#homeSub').textContent = DATA.cover.subtitle || '';
    $('#nfcNote').textContent = DATA.cover.nfc || FALLBACK.cover.nfc;
    $('#heroKitty').innerHTML = KITTY_HEAD;

    // ---- 书信 ----
    const L = DATA.letter;
    $('#letterTo').textContent = L.to || '';
    $('#letterName').textContent = `亲爱的${L.name || '你'}：`;
    $('#letterDate').textContent = L.date || '';
    $('#letterSign').textContent = L.sign ? `—— ${L.sign}` : '';
    if (L.title && $('#title-letter')) $('#title-letter').textContent = L.title;

    $('#letterBody').innerHTML = (L.paragraphs || [])
      .map((p) => `<p class="letter-text">${esc(p)}</p>`)
      .join('');

    // ---- 彩蛋 ----
    const E = DATA.ending;
    if (E.title && $('#title-ending')) $('#title-ending').textContent = E.title;
    $('#endingWish').textContent = E.wish || '';
    $('#endingFrom').textContent = E.from ? `From：${E.from}` : '';
    $('#endingTo').textContent = E.to ? `To：${E.to}` : '';

    // ---- 碎碎念标题 ----
    if (DATA.notes.title && $('#title-notes')) $('#title-notes').textContent = DATA.notes.title;
  }

  /* ------------------------------------------------------------
   * 5. floaters：首页缓慢漂浮的蝴蝶结 / 小星星 / 小圆点
   *    数量依据屏幕宽度决定：手机少一些，避免耗电和拥挤。
   * ------------------------------------------------------------ */
  function createFloaters() {
    const layer = $('#floatLayer');
    if (!layer || prefersReducedMotion()) return;

    const vw = window.innerWidth;
    const scale = vw < 640 ? 0.6 : vw < 1024 ? 0.85 : 1;
    const bowCount = Math.round(7 * scale);
    const starCount = Math.round(10 * scale);
    const dotCount = Math.round(9 * scale);

    const frag = document.createDocumentFragment();

    const addItem = (cls, size, html) => {
      const el = document.createElement('span');
      el.className = `float-item ${cls}`;
      if (html) {
        el.style.width = `${size.toFixed(1)}px`;
        el.style.height = `${size.toFixed(1)}px`;
      }
      el.style.left = `${rand(3, 92).toFixed(1)}%`;
      el.style.top = `${rand(6, 90).toFixed(1)}%`;
      el.style.setProperty('--o', rand(0.18, 0.4).toFixed(3));
      el.style.setProperty('--r', `${rand(-14, 14).toFixed(1)}deg`);
      el.style.animationDuration = `${rand(16, 30).toFixed(1)}s`;
      el.style.animationDelay = `-${rand(0, 24).toFixed(1)}s`;
      if (html) el.innerHTML = html;
      frag.appendChild(el);
    };

    // 蝴蝶结
    for (let i = 0; i < bowCount; i++) {
      const size = rand(18, 30);
      addItem('bow', size, `<svg class="deco-svg" viewBox="0 0 40 30" width="100%" height="100%" aria-hidden="true">${BOW_SVG}</svg>`);
    }
    // 小星星
    for (let i = 0; i < starCount; i++) {
      const size = rand(9, 16);
      addItem('star', size, `<svg class="deco-svg" viewBox="0 0 24 24" width="100%" height="100%" aria-hidden="true">${STAR_SVG}</svg>`);
    }
    // 小圆点
    for (let i = 0; i < dotCount; i++) addItem('dot', 0);

    layer.appendChild(frag);
  }

  /* ------------------------------------------------------------
   * 6. reveal：元素进入视口时淡入
   *    IntersectionObserver 比监听 scroll 更省性能；
   *    弹窗打开时内部元素同样适用。
   * ------------------------------------------------------------ */
  let revealObserver = null;

  function initReveal() {
    const items = document.querySelectorAll('[data-reveal]');

    if (!('IntersectionObserver' in window)) {
      items.forEach((el) => el.classList.add('is-visible'));
      return;
    }

    if (!revealObserver) {
      revealObserver = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible');
            revealObserver.unobserve(entry.target); // 只播放一次
          }
        });
      }, {
        threshold: 0.08,
        rootMargin: '0px 0px -4% 0px'
      });
    }

    items.forEach((el) => {
      if (el.dataset.revealBound) return;
      el.dataset.revealBound = '1';
      revealObserver.observe(el);
    });
  }

  /* ------------------------------------------------------------
   * 7. entries：生成入口卡片（点开后打开对应弹窗）
   * ------------------------------------------------------------ */
  function buildEntries() {
    const grid = $('#entryGrid');
    const E = DATA.entries;
    const map = E || {};
    // order 决定顺序；缺省的弹窗自动补在末尾
    const all = ['gallery', 'letter', 'notes', 'ending'];
    const order = (Array.isArray(map.order) ? map.order : []).filter((k) => all.includes(k));
    all.forEach((k) => { if (!order.includes(k)) order.push(k); });

    const frag = document.createDocumentFragment();
    order.forEach((key, i) => {
      const item = map[key] || {};
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'entry-card';
      btn.setAttribute('data-open', key);
      btn.setAttribute('data-reveal', '');
      btn.style.setProperty('--reveal-delay', `${300 + i * 110}ms`);
      btn.innerHTML = `
        <span class="entry-icon" aria-hidden="true">${ENTRY_ICONS[key] || ''}</span>
        <span class="entry-text">
          <span class="entry-name">${esc(item.name || key)}</span>
          <span class="entry-desc">${esc(item.desc || '')}</span>
        </span>
        ${ARROW_ICON}`;

      // 照片仓库卡片额外显示照片数量
      if (key === 'gallery' && PHOTOS.length) {
        const desc = btn.querySelector('.entry-desc');
        if (desc) desc.textContent = `${PHOTOS.length} 张 · ${item.desc || '我们的光'}`;
      }

      frag.appendChild(btn);
    });

    grid.innerHTML = '';
    grid.appendChild(frag);
  }

  /* ------------------------------------------------------------
   * 8. gallery：照片仓库（分批渲染 + 全屏预览）
   * ------------------------------------------------------------ */

  /** 图片缺失 / 加载中时用的柔和占位图（内联 SVG + Kitty 线稿） */
  function placeholderSVG() {
    const tint = String(DATA.placeholderTint || '#fde6ec').replace('#', '%23');
    const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='800' height='1000' viewBox='0 0 800 1000'>
      <defs>
        <linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>
          <stop offset='0%' stop-color='%23fffaf6'/>
          <stop offset='55%' stop-color='${tint}'/>
          <stop offset='100%' stop-color='%23fdf3d9'/>
        </linearGradient>
      </defs>
      <rect width='800' height='1000' fill='url(%23g)'/>
      <g transform='translate(280 350) scale(2)'>
        <path d='M28 40c-8-6-14-14-9-22 4-6 13-3 17 4 6-3 12-4 18-4h4c6 0 12 1 18 4 4-7 13-10 17-4 5 8-1 16-9 22-2 16-16 28-38 28S30 56 28 40z'
              fill='%23fffdfb' stroke='%23d98a9e' stroke-width='1.6' stroke-opacity='.6'/>
        <g fill='none' stroke='%23d98a9e' stroke-width='1.6' stroke-opacity='.6' stroke-linecap='round'>
          <ellipse cx='47' cy='44' rx='2.6' ry='3.4'/><ellipse cx='73' cy='44' rx='2.6' ry='3.4'/>
          <ellipse cx='60' cy='51' rx='3.6' ry='2.6'/>
          <path d='M31 46l-9 5M31 51l-8 9M89 46l9 5M89 51l8 9'/>
        </g>
      </g>
      <text x='400' y='700' text-anchor='middle' font-family='Helvetica, Arial, sans-serif' font-size='24'
            letter-spacing='8' fill='%239b8482' fill-opacity='.55'>PHOTO</text>
    </svg>`;
    return `data:image/svg+xml,${svg}`;
  }

  /** 照片加载提示 / 失败占位里的小 Kitty（纯线条） */
  const PLACEHOLDER_KITTY = `<svg viewBox="0 0 120 104" aria-hidden="true">${kittySVG()}</svg>`;

  /** 便签的柔和底色（浅色 / 深色各一组，饱和度都很低） */
  const NOTE_TINTS = [
    'rgba(255, 245, 247, 0.95)',
    'rgba(253, 246, 236, 0.95)',
    'rgba(255, 239, 243, 0.95)',
    'rgba(253, 248, 232, 0.95)',
    'rgba(255, 250, 246, 0.95)',
    'rgba(252, 240, 244, 0.95)'
  ];
  const NOTE_TINTS_DARK = [
    'rgba(49, 37, 42, 0.95)',
    'rgba(45, 40, 34, 0.95)',
    'rgba(52, 38, 44, 0.95)',
    'rgba(44, 42, 34, 0.95)',
    'rgba(43, 34, 38, 0.95)',
    'rgba(50, 39, 43, 0.95)'
  ];

  /* ---- 照片仓库状态 ---- */
  const gallery = {
    rendered: 0,   // 已渲染到第几张
    grid: null,
    more: null,
    count: null
  };

  function galleryCardHTML(photo, i) {
    const tilt = rand(-1.8, 1.8).toFixed(2);
    return `
      <div class="polaroid-item" data-reveal
           style="--tilt:${tilt}deg; --reveal-delay:${(i % 4) * 90}ms">
        <figure class="polaroid">
          <span class="polaroid-tape" aria-hidden="true"></span>
          <button class="photo-frame" type="button" data-index="${i}"
                  aria-label="查看第 ${i + 1} 张照片${photo.note ? '：' + esc(photo.note) : ''}">
            <span class="photo-placeholder" aria-hidden="true">${PLACEHOLDER_KITTY}<em>NO.${String(i + 1).padStart(2, '0')}</em></span>
            <img src="${esc(photo.src)}" alt="${esc(photo.note || '生日纪念照片')}" loading="lazy" decoding="async" />
          </button>
          <figcaption class="polaroid-caption">${esc(photo.note || '')}</figcaption>
        </figure>
      </div>`;
  }

  /** 渲染下一批照片（初始一批，之后点「再翻几页」继续） */
  function renderNextBatch() {
    if (!gallery.grid) return;
    const start = gallery.rendered;
    const end = Math.min(start + DATA.galleryBatch, PHOTOS.length);
    if (start >= end) return;

    const html = PHOTOS.slice(start, end).map((p, k) => galleryCardHTML(p, start + k)).join('');
    const tmp = document.createElement('div');
    tmp.innerHTML = html;

    // 绑定图片加载 / 失败 + 点击预览
    Array.from(tmp.children).forEach((item) => {
      const frame = item.querySelector('.photo-frame');
      const img = item.querySelector('img');
      const show = () => frame.classList.add('has-image');
      img.addEventListener('load', show);
      img.addEventListener('error', () => {
        img.src = placeholderSVG();
        img.alt = '照片占位图（请在 images 文件夹放入图片）';
        show();
      });
      if (img.complete && img.naturalWidth > 0) show();
      frame.addEventListener('click', () => lightbox.open(Number(frame.dataset.index)));
    });

    const frag = document.createDocumentFragment();
    while (tmp.firstChild) frag.appendChild(tmp.firstChild);
    gallery.grid.appendChild(frag);
    gallery.rendered = end;

    initReveal();      // 新卡片接入淡入观察
    updateGalleryMore();
  }

  function updateGalleryMore() {
    if (!gallery.more) return;
    const left = PHOTOS.length - gallery.rendered;
    if (left > 0) {
      gallery.more.innerHTML = `<button type="button" id="galleryMoreBtn">再翻几页 · 还剩 ${left} 张</button>`;
      $('#galleryMoreBtn').addEventListener('click', renderNextBatch);
    } else {
      gallery.more.innerHTML = PHOTOS.length ? `<p>— 全部看完啦，每一张都很好 —</p>` : '';
    }
    if (gallery.count) {
      gallery.count.textContent = PHOTOS.length
        ? `共 ${PHOTOS.length} 张 · 已显示 ${gallery.rendered} 张`
        : '';
    }
  }

  function buildGallery() {
    gallery.grid = $('#galleryGrid');
    gallery.more = $('#galleryMore');
    gallery.count = $('#galleryCount');
    const jump = $('#galleryJump');

    if (!PHOTOS.length) {
      gallery.grid.innerHTML = `<div class="empty-state">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <rect x="3" y="5" width="18" height="14" rx="2.5" /><circle cx="9" cy="10" r="1.8" /><path d="M4 17l5-4.5 3.5 3 3-2.5L20 17" />
          </svg>
          <span>照片还在慢慢冲洗中……</span>
        </div>`;
      if (gallery.more) gallery.more.innerHTML = '';
      return;
    }

    // 快速翻页：每 20 张一组（照片很多时可以直达后面的页）
    if (jump) {
      if (PHOTOS.length > DATA.galleryBatch) {
        const step = DATA.galleryBatch * 2;
        const groups = Math.ceil(PHOTOS.length / step);
        let html = '';
        for (let g = 0; g < groups; g++) {
          const from = g * step + 1;
          const to = Math.min(PHOTOS.length, (g + 1) * step);
          html += `<button type="button" data-jump="${g}">${from}–${to}</button>`;
        }
        jump.innerHTML = html;
        jump.addEventListener('click', (e) => {
          const btn = e.target.closest('button[data-jump]');
          if (!btn) return;
          // 先把照片一次性补齐到目标位置，再滚过去
          const target = Math.min(PHOTOS.length, (Number(btn.dataset.jump) + 1) * step);
          while (gallery.rendered < target) renderNextBatch();
          jump.querySelectorAll('button').forEach((b) => b.classList.toggle('is-active', b === btn));
          const body = $('#galleryBody');
          const first = gallery.grid.children[Number(btn.dataset.jump) * step];
          if (first && body) {
            const delta = first.getBoundingClientRect().top - body.getBoundingClientRect().top;
            body.scrollTo({ top: body.scrollTop + delta - 8, behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
          }
        });
      } else {
        jump.innerHTML = '';
      }
    }

    renderNextBatch();
  }

  /* -------------------- 全屏大图预览 -------------------- */
  const lightbox = {
    root: null,
    img: null,
    index: 0,
    isOpen: false,
    lastFocus: null,

    init() {
      this.root = $('#lightbox');
      if (!this.root) return;
      this.img = $('#lightboxImg');
      this.caption = $('#lightboxCaption');
      this.counter = $('#lightboxCounter');

      $('#lightboxClose').addEventListener('click', (e) => { e.stopPropagation(); this.close(); });
      $('#lightboxPrev').addEventListener('click', (e) => { e.stopPropagation(); this.step(-1); });
      $('#lightboxNext').addEventListener('click', (e) => { e.stopPropagation(); this.step(1); });

      // 点击空白处关闭：点到按钮 / 图片 / 备注文字都不关
      this.root.addEventListener('click', (e) => {
        if (e.target.closest('button, img, p')) return;
        this.close();
      });
      // 键盘：← → 切换，Esc 关闭（在 sheets 统一处理，这里只处理预览）
      window.addEventListener('keydown', (e) => {
        if (!this.isOpen) return;
        if (e.key === 'Escape') this.close();
        else if (e.key === 'ArrowLeft') this.step(-1);
        else if (e.key === 'ArrowRight') this.step(1);
      });

      // 手机端左右滑动切换
      let touchX = null;
      this.root.addEventListener('touchstart', (e) => {
        touchX = e.touches[0].clientX;
      }, { passive: true });
      this.root.addEventListener('touchend', (e) => {
        if (touchX === null) return;
        const dx = e.changedTouches[0].clientX - touchX;
        touchX = null;
        if (Math.abs(dx) > 55) this.step(dx > 0 ? -1 : 1);
      }, { passive: true });
    },

    render() {
      const p = PHOTOS[this.index];
      if (!p) return;
      this.img.onerror = null;
      this.img.src = p.src;
      this.img.alt = p.note || `第 ${this.index + 1} 张照片`;
      this.caption.textContent = p.note || '';
      this.counter.textContent =
        `${String(this.index + 1).padStart(2, '0')} / ${String(PHOTOS.length).padStart(2, '0')}`;
      // 图片找不到时用占位图顶上，不出现破图
      this.img.onerror = () => { this.img.onerror = null; this.img.src = placeholderSVG(); };
    },

    open(index) {
      if (!PHOTOS.length) return;
      this.lastFocus = document.activeElement;
      this.index = Math.max(0, Math.min(index, PHOTOS.length - 1));
      this.render();
      this.isOpen = true;
      this.root.classList.add('is-open');
      this.root.setAttribute('aria-hidden', 'false');
      lockScroll(true);
      setTimeout(() => $('#lightboxClose')?.focus({ preventScroll: true }), 60);
      this.preload();
    },

    step(dir) {
      if (!this.isOpen || PHOTOS.length < 2) return;
      this.index = (this.index + dir + PHOTOS.length) % PHOTOS.length;
      this.render();
      this.preload();
    },

    /** 预加载相邻图片，切换更顺滑 */
    preload() {
      const n = PHOTOS.length;
      if (n < 2) return;
      [this.index + 1, this.index - 1].forEach((i) => {
        const p = PHOTOS[(i + n) % n];
        if (p) { const im = new Image(); im.src = p.src; }
      });
    },

    close() {
      if (!this.isOpen) return;
      this.isOpen = false;
      this.root.classList.remove('is-open');
      this.root.setAttribute('aria-hidden', 'true');
      lockScroll(false);
      this.lastFocus?.focus?.({ preventScroll: true });
    }
  };

  /* ------------------------------------------------------------
   * 9. notes：碎碎念便签
   * ------------------------------------------------------------ */
  function noteTints() {
    return isDark() ? NOTE_TINTS_DARK : NOTE_TINTS;
  }

  function buildNotes() {
    const grid = $('#noteGrid');
    const items = (DATA.notes.items || []).filter((n) => n && n.text);

    if (!items.length) {
      grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1;"><span>还没有悄悄话哦</span></div>`;
      return;
    }

    const tints = noteTints();
    const frag = document.createDocumentFragment();

    items.forEach((n, i) => {
      const card = document.createElement('div');
      card.className = 'note-card';
      card.setAttribute('data-reveal', '');
      card.style.setProperty('--reveal-delay', `${(i % 3) * 140}ms`);
      card.style.setProperty('--tilt', `${rand(-1.4, 1.4).toFixed(2)}deg`);
      card.style.setProperty('--note-bg', tints[i % tints.length]);
      card.innerHTML = `
        <p class="note-index" aria-hidden="true">NO.${String(i + 1).padStart(2, '0')}</p>
        <p class="note-text">${esc(n.text)}</p>`;
      frag.appendChild(card);
    });

    grid.innerHTML = '';
    grid.appendChild(frag);
    initReveal();
  }

  /* ------------------------------------------------------------
   * 10. sheets：弹窗开关
   *   - 打开：显示面板、锁定背景滚动、焦点移入、触发对应初始化
   *   - 关闭：Esc / 关闭按钮 / 点遮罩 / 面板下滑
   *   - 历史：打开时写入 hash，手机返回键可以关闭弹窗
   * ------------------------------------------------------------ */
  let openedKey = null;
  let lockCount = 0;

  /** 背景滚动锁：同一时间可能有「弹窗 + 大图预览」两层，用计数避免提前解锁 */
  function lockScroll(lock) {
    lockCount = Math.max(0, lockCount + (lock ? 1 : -1));
    document.body.classList.toggle('is-locked', lockCount > 0);
  }

  /**
   * 打开弹窗时往浏览器历史里压一条记录，好处是：
   *   - 手机返回键 / 侧滑 = 关闭弹窗，而不是直接离开页面；
   *   - 首次打开页面时「再按返回」才离开，不影响正常体验。
   * depth 记录我们自己压了多少条历史，关弹窗时主动 history.back() 退回去。
   */
  let depth = 0;

  const sheets = {
    el(key) { return document.querySelector(`.sheet[data-sheet="${key}"]`); },

    open(key) {
      const sheet = this.el(key);
      if (!sheet) return;
      if (openedKey === key) return;

      if (openedKey) this.close(openedKey, true); // 直接切换另一张

      sheet.classList.add('is-open');
      sheet.setAttribute('aria-hidden', 'false');
      const body = sheet.querySelector('.sheet-body');
      if (body) body.scrollTop = 0;
      lockScroll(true);
      openedKey = key;

      // 打开彩蛋时触发蛋糕动画
      if (key === 'ending') ending.replay();

      // 弹窗内元素的淡入（等面板动画开始后再观察）
      requestAnimationFrame(() => initReveal());

      // 焦点移入面板，键盘用户可以用 Tab 继续操作
      setTimeout(() => {
        sheet.querySelector('.sheet-close')?.focus({ preventScroll: true });
      }, 120);

      // 写入 hash，方便手机返回键关闭（不刷新页面）
      try {
        if (history.pushState) {
          history.pushState({ sheet: key }, '', `#${key}`);
          depth++;
        }
      } catch (_) { /* file:// 等环境可能不支持，忽略即可 */ }
    },

    /** silent = true 表示「历史记录已经由 popstate 处理」，不再回退 */
    close(key = openedKey, silent = false) {
      const sheet = key ? this.el(key) : null;
      if (!sheet) return;
      sheet.classList.remove('is-open');
      sheet.setAttribute('aria-hidden', 'true');
      if (openedKey === key) openedKey = null;
      lockScroll(false);

      // 关掉大图预览（如果还开着）：预览本身不写历史，这里一起收掉更干净
      if (lightbox.isOpen) lightbox.close();

      if (!silent && depth > 0) {
        // 把历史退回到打开弹窗之前：后退键不会「卡在」已经关掉的弹窗上
        depth--;
        try { history.back(); } catch (_) { /* ignore */ }
      }
    },

    closeAll() { if (openedKey) this.close(openedKey); }
  };

  function initSheets() {
    // 入口卡片
    document.querySelectorAll('[data-open]').forEach((btn) => {
      btn.addEventListener('click', () => sheets.open(btn.dataset.open));
    });

    // 关闭按钮 / 遮罩
    document.querySelectorAll('.sheet [data-close]').forEach((el) => {
      el.addEventListener('click', () => sheets.close());
    });

    // Esc 关闭弹窗（大图预览的 Esc 由 lightbox 自己处理）
    document.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape' || lightbox.isOpen) return;
      sheets.closeAll();
    });

    // 浏览器后退 / 前进：同步弹窗状态
    window.addEventListener('popstate', () => {
      depth = 0;
      const key = (location.hash || '').replace('#', '');
      if (key && sheets.el(key)) {
        sheets.open(key);          // 前进到某个弹窗
      } else if (openedKey) {
        sheets.close(openedKey, true);  // 后退：关闭当前弹窗，不再回退历史
      }
    });

    // 用 #letter 这类带锚点的链接打开页面时，加载完成后自动展开对应弹窗
    const initial = (location.hash || '').replace('#', '');
    if (initial && sheets.el(initial)) {
      // 直接替换成不带 hash 的首页地址，再打开弹窗：
      // 这样关闭弹窗时后退键不会遇到「空 hash」的历史记录
      try {
        if (history.replaceState) history.replaceState(null, '', location.pathname + location.search);
      } catch (_) { /* ignore */ }
      setTimeout(() => sheets.open(initial), 1500);
    }

    // ---- 手机：在面板头部或内容顶部往下滑，关闭弹窗 ----
    document.querySelectorAll('.sheet').forEach((sheet) => {
      let startY = null;
      let moved = 0;
      const header = sheet.querySelector('.sheet-header');
      const body = sheet.querySelector('.sheet-body');

      const onStart = (e) => {
        const touch = e.touches[0];
        // 只有「按在头部」或「滚动内容已经在顶部」时才允许下拉关闭，
        // 避免正常滚动照片时误触
        if ((header && header.contains(e.target)) || (body && body.scrollTop <= 0)) {
          startY = touch.clientY;
          moved = 0;
        } else {
          startY = null;
        }
      };
      const onMove = (e) => {
        if (startY === null) return;
        moved = e.touches[0].clientY - startY;
      };
      const onEnd = () => {
        if (startY === null) return;
        const shouldClose = moved > 110;
        startY = null;
        if (shouldClose) sheets.close();
      };

      sheet.addEventListener('touchstart', onStart, { passive: true });
      sheet.addEventListener('touchmove', onMove, { passive: true });
      sheet.addEventListener('touchend', onEnd, { passive: true });
    });
  }

  /* ------------------------------------------------------------
   * 11. music：右下角背景音乐按钮
   *     严格不自动播放：必须用户点击后才开始。
   * ------------------------------------------------------------ */
  function initMusic() {
    const btn = $('#musicBtn');
    const tip = $('#musicTip');
    const tracks = (DATA.music.tracks || []).filter((t) => t && t.src);

    if (!btn) return;
    // 没有配置音乐：隐藏按钮，保持页面干净
    if (!tracks.length) {
      btn.hidden = true;
      if (tip) tip.hidden = true;
      return;
    }

    const audio = new Audio();
    audio.preload = 'metadata';
    const rawVolume = Number(DATA.music.volume);
    audio.volume = isNaN(rawVolume) ? 0.35 : Math.min(1, Math.max(0, rawVolume));
    audio.loop = tracks.length === 1; // 只有一首时循环
    audio.src = tracks[0].src;

    let trackIndex = 0;
    let wantsPlay = false; // 用户是否希望播放
    let available = true;  // 音频文件是否存在

    const ICON_PLAY = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18V6.5l10-2V16"/><circle cx="6.6" cy="18" r="2.6"/><circle cx="16.6" cy="16" r="2.6"/></svg>`;
    const ICON_PAUSE = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 7v10M15 7v10"/></svg>`;
    const ICON_MUTED = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18V6.5l10-2V16"/><circle cx="6.6" cy="18" r="2.6"/><circle cx="16.6" cy="16" r="2.6"/><path d="M3 3l18 18" opacity=".6"/></svg>`;

    function setState(playing) {
      btn.dataset.playing = playing ? 'true' : 'false';
      btn.setAttribute('aria-pressed', playing ? 'true' : 'false');
      btn.setAttribute('aria-label', playing ? '暂停背景音乐' : '播放背景音乐');
      btn.innerHTML = available ? (playing ? ICON_PAUSE : ICON_PLAY) : ICON_MUTED;
    }

    function showTip(text) {
      if (!tip) return;
      tip.textContent = text;
      tip.classList.add('is-shown');
      clearTimeout(showTip._t);
      showTip._t = setTimeout(() => tip.classList.remove('is-shown'), 3600);
    }

    function play() {
      wantsPlay = true;
      const p = audio.play();
      if (p && typeof p.catch === 'function') {
        p.then(() => setState(true)).catch(() => {
          // 被浏览器拦截或被拒绝：保持静音状态，等用户再点
          wantsPlay = false;
          setState(false);
        });
      } else {
        setState(true);
      }
    }

    function pause() {
      wantsPlay = false;
      audio.pause();
      setState(false);
    }

    btn.addEventListener('click', () => {
      if (!available) { showTip('还没有放音乐哦'); return; }
      if (audio.paused) play(); else pause();
    });

    // 多首音乐：播完自动切下一首
    audio.addEventListener('ended', () => {
      if (tracks.length < 2) return;
      trackIndex = (trackIndex + 1) % tracks.length;
      audio.src = tracks[trackIndex].src;
      if (wantsPlay) play();
    });

    // 音频文件缺失：按钮变成带斜线的音符，不报错、不卡住
    audio.addEventListener('error', () => {
      available = false;
      wantsPlay = false;
      btn.dataset.playing = 'false';
      btn.setAttribute('aria-label', '背景音乐暂不可用');
      btn.innerHTML = ICON_MUTED;
      showTip('音乐还在路上');
    });

    setState(false);

    // 首次进入的温柔提示（用户没点之前不会出声）
    setTimeout(() => { if (available && audio.paused) showTip('点一下，有声音'); }, 4200);

    // 切到后台自动暂停；回到前台若之前是播放状态则恢复
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        if (!audio.paused) { audio.dataset.resume = '1'; audio.pause(); setState(false); }
      } else if (audio.dataset.resume === '1' && wantsPlay) {
        delete audio.dataset.resume;
        play();
      }
    });
  }

  /* ------------------------------------------------------------
   * 12. ending：彩蛋（线条蛋糕升起 + 星光散开）
   *     每次打开彩蛋弹窗都重新播放一次
   * ------------------------------------------------------------ */
  const ending = {
    built: false,

    /** 第一次打开时初始化：量线长、生成星光 */
    build() {
      if (this.built) return;
      this.built = true;

      const cake = $('.cake-svg');
      if (cake) {
        cake.querySelectorAll('.draw').forEach((path) => {
          try {
            path.style.setProperty('--len', Math.ceil(path.getTotalLength()) + 2);
          } catch (_) {
            path.style.setProperty('--len', 500);
          }
        });
      }

      // 散开的细碎星光：位置围绕蛋糕顶部
      const box = $('#cakeSparkles');
      if (box && !prefersReducedMotion()) {
        const count = window.innerWidth < 640 ? 14 : 22;
        let html = '';
        for (let i = 0; i < count; i++) {
          html += `<span class="sparkle" style="left:${rand(8, 92).toFixed(1)}%; top:${rand(20, 55).toFixed(1)}%;
            width:${rand(3, 5).toFixed(1)}px; height:${rand(3, 5).toFixed(1)}px;
            --dx:${rand(-55, 55).toFixed(0)}px; --dy:${rand(-130, -50).toFixed(0)}px;
            --dur:${rand(5, 8).toFixed(1)}s; --delay:${(i * 0.16).toFixed(2)}s;"></span>`;
        }
        box.innerHTML = html;
      }
    },

    /** 每次打开彩蛋弹窗：重置动画并重新播放 */
    replay() {
      this.build();
      const panel = $('#endingPanel');
      if (!panel) return;
      panel.classList.remove('is-celebrated');
      void panel.offsetWidth;                       // 强制回流，让动画可以重播
      setTimeout(() => panel.classList.add('is-celebrated'), 380);
    }
  };

  /* ------------------------------------------------------------
   * 13. boot：加载过渡与初始化
   * ------------------------------------------------------------ */

  // 首屏全程禁用过渡：避免 Tailwind 编译完成时出现「样式跳变 / 闪烁」
  const killSwitch = document.createElement('style');
  killSwitch.id = 'no-transition';
  killSwitch.textContent = `*, *::before, *::after {
    transition: none !important;
    animation-duration: 0s !important;
    animation-delay: 0s !important;
  }`;
  document.head.appendChild(killSwitch);

  /** Tailwind 浏览器版会异步编译样式，等它就绪或最多等 1.2 秒（加载失败也不会卡住） */
  function waitForTailwind() {
    return new Promise((resolve) => {
      let done = false;
      const finish = () => { if (!done) { done = true; resolve(); } };

      // 兜底轮询：sr-only 生效说明 preflight 已经跑过
      const probe = document.createElement('div');
      probe.className = 'sr-only';
      probe.style.position = 'absolute';
      document.body.appendChild(probe);

      const started = performance.now();
      (function tick() {
        if (done) return;
        const cs = getComputedStyle(probe);
        if (cs.width === '1px' && cs.position === 'absolute') {
          probe.remove();
          return finish();
        }
        if (performance.now() - started > 1200) {
          probe.remove();
          // CDN 没加载成功时也要能正常看：恢复过渡，保证自定义样式照常柔和显示
          killSwitch.remove();
          return finish();
        }
        setTimeout(tick, 60);
      })();
    });
  }

  function ready() {
    // 回到页面顶部，避免刷新后停在半中间
    if ('scrollRestoration' in history) history.scrollRestoration = 'manual';

    // ---- 生成内容（全部在首屏一次完成，弹窗内容也是预先渲染好的） ----
    hydrate();
    buildEntries();
    buildGallery();
    buildNotes();
    createFloaters();
    initReveal();                                   // 收集所有 [data-reveal]
    lightbox.init();
    initSheets();
    initMusic();
    ending.build();                                 // 量线长（蛋糕动画第一次打开时播放）

    // ---- 撤掉「禁用过渡」，连续两帧后解除内容隐藏态，首页平滑浮现 ----
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        killSwitch.remove();
        document.body.classList.add('is-ready');
      });
    });

    // ---- 加载层缓慢淡出（中间是线条 Kitty） ----
    const loader = $('#loader');
    setTimeout(() => {
      loader?.classList.add('is-done');
      setTimeout(() => loader?.remove(), 1600);
    }, 420);

    // 系统深色模式切换时，重新计算便签底色（只换颜色，不重建 DOM）
    const darkMQ = window.matchMedia('(prefers-color-scheme: dark)');
    darkMQ.addEventListener?.('change', () => {
      const tints = noteTints();
      document.querySelectorAll('.note-card').forEach((card, i) => {
        card.style.setProperty('--note-bg', tints[i % tints.length]);
      });
    });
  }

  function boot() {
    waitForTailwind().then(ready);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
})();
