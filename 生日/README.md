# 🎀 生日纪念页 · 使用与部署说明（Hello Kitty 可爱温柔风 · 第二版）

一个纯静态的生日小盒子：**HTML + Tailwind CSS + 原生 JS**，无后端、无数据库、无登录，
所有访客只能浏览。适合把链接写进 NFC 卡片送给朋友。

> **第二版变化**：从「一整页长滚动」改成了 **首页封面 + 入口卡片**，
> 点卡片 → 打开独立弹窗（照片仓库 / 一封信 / 碎碎念 / 拆彩蛋），关闭后回到首页。
> 手机端单列留白、电脑端铺满多列的自适应逻辑保持不变。

```
生日/
├── index.html               页面骨架（一般不用改）
├── config.js                ★ 所有文字、照片、便签、音乐都在这里配置
├── css/
│   └── style.css            样式：粉白黄配色、线条 Kitty 装饰、弹窗动画、深色模式
├── js/
│   └── app.js               脚本：入口卡片、弹窗、相册预览、音乐、彩蛋
├── images/                  ★ 放照片（photo-01.jpg …）
├── music/                   ★ 放背景音乐（bgm.mp3）
├── tools/
│   └── make-placeholder.html  本地生成占位图的小工具（可选，不参与线上页面）
├── vercel.json              部署配置（缓存、URL 规则）
├── .gitignore / .gitattributes
└── README.md                本说明
```

> 现在 `images/` 和 `music/` 里还没有文件，照片仓库会自动显示**粉白色占位图**，
> 音乐按钮会变成「音乐还在路上」。把你的照片和音乐放进去即可自动生效。

---

## 一、页面结构（第二版）

| 位置 | 内容 | 在哪里改 |
| --- | --- | --- |
| 首页封面 | 线条 Kitty 头像、大标题「生日快乐」、副标题、漂浮的蝴蝶结/星星 | `config.js` → `cover` |
| 首页入口卡片 | 4 张卡片：照片仓库 / 一封信 / 碎碎念 / 拆彩蛋 | `config.js` → `entries` |
| 照片仓库弹窗 | 大量拍立得照片，点单张看大图，可左右切换 | `config.js` → `photos` |
| 一封信弹窗 | 信纸卡片 + 长段落文字 | `config.js` → `letter` |
| 碎碎念弹窗 | 半透明便签 | `config.js` → `notes` |
| 拆彩蛋弹窗 | 线条蛋糕升起 + 星光散开 + 落款日期 | `config.js` → `ending` |
| 首页底部 | NFC 提示小字（保留原文案） | `config.js` → `cover.nfc` |

**交互操作**

- 点入口卡片 → 弹窗从下往上轻轻浮起；关闭方式：右上角 ✕、点弹窗外的空白处、按 `Esc`、
  手机上从弹窗顶部往下滑，或者按手机的返回键。
- 照片仓库：弹窗内部自己滚动；照片很多时先显示一批，底部「再翻几页」继续加载；
  顶部还能按批「快速翻页」。
- 点单张照片 → 全屏大图（白色相纸边），左右按钮 / 键盘 ← → / 手机左右滑动切换，图片下方显示备注；
  点空白处或 `Esc` 关闭。
- 右下角音符按钮：点一下才播放背景音乐，**绝不自动播放**。

---

## 二、怎么替换文字

**所有文字都集中在 `config.js`**，用电脑记事本 / VS Code 打开即可，改完保存、刷新页面就生效。

| 想改的内容 | 在 config.js 里找 | 说明 |
| --- | --- | --- |
| 封面顶部小字 | `cover.eyebrow` | 默认 `for my dearest` |
| 封面大标题 | `cover.titleChars` | 四个字，想换就四个都换，如 `['生','日','快','乐']` |
| 封面副标题 | `cover.subtitle` | 一句话即可 |
| 底部 NFC 小字 | `cover.nfc` | 默认「轻触 NFC 卡片，与你奔赴这一份专属温柔」 |
| 入口卡片的名字/说明 | `entries.gallery / letter / notes / ending` | 改 `name`（卡片标题）和 `desc`（小字说明） |
| 入口卡片顺序 | `entries.order` | 改成 `['letter','gallery','notes','ending']` 等任意顺序 |
| 信的标题 | `letter.title` | 默认「写给你的一封信」 |
| 信的收信人 / 称呼 | `letter.to`、`letter.name` | 显示为「致 XXX」「亲爱的 XXX：」 |
| 信的正文 | `letter.paragraphs` | **每个字符串 = 一个段落**，想写很长就多加几条 |
| 信的日期 / 落款 | `letter.date`、`letter.sign` | 显示为「—— 落款」 |
| 碎碎念标题 | `notes.title` | |
| 便签短句 | `notes.items` | 每张便签一句，4~9 条最合适 |
| 彩蛋标题 | `ending.title` | 默认「拆开看看」 |
| 蛋糕上方祝福 | `ending.wish` | |
| 落款 / 日期 | `ending.from`、`ending.to` | 显示为「From：…」「To：…」 |

**修改注意事项（很重要）**

1. 字符串一律用英文引号 `'...'` 或 `"..."`，中文标点不行。
2. 每一项后面要有英文逗号 `,`，最后一项可以不加。
3. 不要删除 `window.BIRTHDAY_DATA = {` 和末尾的 `};`。
4. 改完如果页面空白，多半是**漏了逗号或引号**，按 `F12` 打开控制台会指出第几行出错。
5. 文字里可以写普通标点，**不要写 HTML 标签**（会被当成纯文字显示）。

---

## 三、怎么替换 / 新增图片

### 1. 放图片

- 所有照片放在项目根目录的 **`images/` 文件夹**里。
- 推荐命名：`photo-01.jpg`、`photo-02.jpg` …… 按顺序编号。
- 支持格式：`.jpg` `.jpeg` `.png` `.webp`（优先 jpg / webp，体积小）。
- **建议每张压缩到 300KB 以内、长边 1600px 左右**，手机打开更快：
  - 在线压缩：<https://squoosh.app>（选 MozJPEG，质量 75 左右）

### 2. 在 config.js 里登记

```js
photos: [
  { src: 'images/photo-01.jpg', note: '那天风很轻，你笑得很好看' },
  { src: 'images/photo-02.jpg', note: '下午三点的光，落在你的肩上' }
],
```

- `src`：**相对路径**，就是 `images/文件名.jpg`（大小写要和文件名完全一致，
  线上服务器区分大小写，`Photo-01.JPG` ≠ `photo-01.jpg`）。
- `note`：照片下方那一行简短备注，不想要就写 `note: ''`。
- **新增照片**：复制一整行 `{ ... },` 粘贴到末尾，改文件名和备注即可。
  照片仓库会自动排布（手机单列 / 平板 2 列 / 电脑 3~4 列），**数量没有上限**。
- 删除照片：删掉那一行即可。

### 3. 照片很多怎么办

- 页面默认每批渲染 **12 张**，滚动到底点点「再翻几页」继续，避免一次加载太多卡顿。
- 想让一批更多 / 更少：改 `config.js` 底部的 `galleryBatch: 12`。
- 照片特别多（比如 100 张以上）时，请在电脑上把图片压缩好再上传，否则手机流量和加载会比较吃力。

### 4. 效果说明

- 拍立得卡片默认 **4:5 竖构图**，照片居中裁切填满。
  想看完整的横图：在 `css/style.css` 里把 `.photo-frame` 的 `aspect-ratio: 4 / 5` 改成 `4 / 3`。
- 照片自动降一点饱和度、降一点对比度，统一成柔光色调。
- 图片永远不超出屏幕宽度；缺失的图片会自动显示**粉白占位图**，不会出现破图。

### 5. 想快速生成占位图？

双击 `tools/make-placeholder.html`，在浏览器点「生成并下载」，
会下载 `photo-01.jpg` … 到下载文件夹，拖进 `images/` 即可（之后可以删掉 tools 文件夹）。

---

## 四、怎么替换背景音乐

### 1. 准备音乐

- 推荐 `.mp3`（兼容性最好），也支持 `.m4a`、`.wav`、`.ogg`。
- **文件名用纯英文小写**，不要有空格和中文，例如 `bgm.mp3`。
- 建议单曲 1~3 分钟、体积 1~3MB。太大可以先用 <https://mp3smaller.com> 压缩。
- 请使用你有权利使用的音乐（自己录的、无版权音乐库、已购歌曲）。

### 2. 放进 `music/` 文件夹

```
music/bgm.mp3
```

### 3. 在 config.js 里登记

```js
music: {
  tracks: [
    { src: 'music/bgm.mp3', title: '温柔小曲' }
  ],
  volume: 0.35      // 0 ~ 1，0.35 左右比较柔和
},
```

- 多首会**按顺序播放、播完自动接下一首、最后循环**：
  ```js
  tracks: [
    { src: 'music/bgm-1.mp3', title: '第一首' },
    { src: 'music/bgm-2.mp3', title: '第二首' }
  ]
  ```
- 不放音乐：改成 `tracks: []`，右下角按钮会自动隐藏。

### 4. 关于自动播放

**不会自动播放**。访客点右下角音符按钮才开始；首次进入 4 秒后会有小小提示「点一下，有声音」；
切到别的 App / 标签页会自动暂停，回来时恢复。

> iOS 手机侧边静音键打开时，Safari 听不到网页声音，是系统行为，提醒朋友打开声音即可。

---

## 五、本地预览

直接双击 `index.html` 也能打开；想用手机预览（更接近真实效果）：

- 装了 VS Code：安装插件 **Live Server** → 右键 `index.html` → *Open with Live Server*。
- 装了 Node.js：在本文件夹打开终端，运行
  ```bash
  npx serve .
  ```
  手机连同一个 Wi-Fi，访问终端里显示的 `http://192.168.x.x:3000`。

预览时按 `F12` → 点设备图标（Ctrl + Shift + M）切换手机视图，检查单列布局与弹窗效果。

---

## 六、Vercel 免费部署（分步教程）

> 两种方式任选一种。**方式 A 带 GitHub，之后改内容最方便（自动重新部署）；
> 方式 B 最快，不用 GitHub，但以后修改需要重新拖一次。**

### 方式 A：GitHub + Vercel（推荐）

**第 1 步：注册账号**

1. 打开 <https://github.com> 注册 / 登录 GitHub（免费）。
2. 打开 <https://vercel.com> → *Sign Up* → **Continue with GitHub**，授权登录。

**第 2 步：把项目上传到 GitHub**

1. GitHub 右上角 **+** → *New repository*，仓库名随意（如 `birthday`），点 *Create repository*。
2. 在仓库页面点 **uploading an existing file**。
3. 把项目里的**全部文件和文件夹**（`index.html`、`config.js`、`css`、`js`、`images`、`music`、
   `vercel.json` 等）拖进去，点 **Commit changes**。
   > ⚠️ 保证 `index.html` 在仓库**根目录**，不能变成 `birthday/生日/index.html` 多一层，
   > 否则打开会是 404。

**第 3 步：导入到 Vercel**

1. Vercel 控制台点 **Add New… → Project**。
2. 找到刚建的仓库 → **Import**。
3. 配置保持默认：
   - Framework Preset：**Other**
   - Root Directory：`./`
   - Build Command：**留空**
   - Output Directory：**留空**
4. 点 **Deploy**，等 10~30 秒。

**第 4 步：拿到链接**

点 **Visit**，得到形如 `https://birthday-xxxx.vercel.app` 的网址。
这个默认网址一直可用；想更好记可在 *Settings → Domains* 添加一个自定义 `.vercel.app` 域名，
或绑定自己的域名（到域名商处按提示配置 CNAME 即可）。

**第 5 步：写入 NFC 标签**

用手机的 NFC 工具写入一条 **URL / 网址** 记录，内容填上面的网址。
- 安卓：「NFC Tools」或 NXP 的「TagWriter」，选择 *写标签 → URL*。
- iPhone：系统不开放第三方 App 直接写标签，可以（1）用安卓手机代为写入；
  （2）买出厂已写好网址的 NFC 贴纸 / 卡片；或用「快捷指令 → 自动化 → NFC」。
- 标签建议用 **NTAG213 / NTAG215**。先写入、贴一下确认能打开，再决定是否锁定。

### 方式 B：不用 GitHub，直接拖拽部署（Vercel Drop）

1. 电脑浏览器打开 <https://vercel.com/drop>。
2. 把**整个项目文件夹**拖进页面中间的拖拽区域。
3. 稍等几秒，会得到一条 `*.vercel.app` 的链接。
4. 以后修改内容：回到同一个页面重新拖一次；或之后把它认领到自己的账号下管理。

> 找不到拖拽入口时，也可以用命令行（需安装 Node.js），在项目文件夹执行：
> ```bash
> npx vercel login     # 首次登录
> npx vercel --prod    # 发布，终端会输出网址
> ```

---

## 七、备注说明（重要）

- 这是**静态只读页面**：没有后端、数据库和登录功能，所有人打开链接**只能浏览**。
- 想改文字、加照片、换音乐，必须在**电脑本地**修改项目文件，然后**重新部署**更新网址。
- **手机浏览器打开网址时无法上传、添加图片**，也不会有任何编辑按钮——这是设计如此。
- 页面里没有任何登录框、弹窗广告、实时同步、后端请求。

**改完怎么更新？**

- 方式 A（GitHub）：在 GitHub 网页上点开 `config.js` → 铅笔图标编辑 → *Commit changes*，
  Vercel 会自动重新部署，一般 30 秒内生效，**网址不变**。
  加照片：*Add file → Upload files* 上传到 `images/`，再改 `config.js` 里的 `photos`。
- 方式 B（Drop / CLI）：重新拖一次文件夹，或重新执行 `npx vercel --prod`。

改完如果浏览器还是旧内容，按 `Ctrl + F5` 强制刷新，或等一两分钟。

---

## 八、常见问题

**Q：点卡片没反应 / 弹窗出不来？**
检查 `config.js` 是否改坏了（缺逗号、缺引号）。按 `F12` → Console，会指出第几行出错。

**Q：深色模式怎么切换？**
自动跟随系统（手机「设置 → 显示 → 深色模式」）。深色版是柔雾紫粉色，同样低对比。

**Q：动画能再慢 / 快一点吗？**
- 全局淡入时长：`css/style.css` 顶部 `--dur-slow`（默认 1500ms）。
- 封面文字依次淡入：`js/app.js` 中 `hydrate()` 里的 `260 + i * 180`（数字越大越慢）。
- 弹窗浮起速度：`css/style.css` 中 `.sheet-panel` 的 `transition`。
- 漂浮数量 / 大小：`js/app.js` 中 `createFloaters()` 的 `bowCount / starCount / dotCount`。

**Q：想减少动画、更省电？**
手机开启系统「减弱动态效果 / 减少动画」，页面会自动关掉漂浮与摇摆，只保留基础淡入。

**Q：照片太多，打开很慢？**
先压缩图片（每张 300KB 以内）；照片仓库是分批渲染的，不会一次全部加载。

**Q：Tailwind 是 CDN 加载的，会慢吗？**
脚本来自 jsDelivr，首次加载后浏览器会缓存；页面做了「等样式就绪再淡入」的处理，不会先看到裸页面。
想更快可以把这个脚本下载到项目里（浏览器打开 <https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4>，
全选另存为 `js/tailwind-browser.js`），再把 `index.html` 里那一行换成
`<script src="js/tailwind-browser.js"></script>`。

想彻底改成本地编译的 CSS（需要 Node.js，一次性操作）：

```bash
npm install tailwindcss @tailwindcss/cli
```

新建 `src/input.css`：

```css
@import "tailwindcss";
@source "../index.html";
```

编译：

```bash
npx @tailwindcss/cli -i src/input.css -o css/tailwind.css --watch
```

然后在 `index.html` 里删掉 CDN 那一行，换成
`<link rel="stylesheet" href="css/tailwind.css" />`（放在 `css/style.css` 之前），重新部署。

---

## 九、想更懂一点：页面是怎么跑的

1. `index.html` 先加载 Tailwind（浏览器版）与 `css/style.css`，再顺序加载 `config.js`、`js/app.js`。
2. `app.js` 等 Tailwind 编译完成（检查 `sr-only` 是否生效，最多 1.2 秒；CDN 失败也能正常显示），
   然后把文字填进页面、生成入口卡片和照片仓库，再**缓慢淡出加载层**（中间是线条 Kitty），首页柔和浮现。
3. 弹窗内容在首页加载时就已生成（打开瞬间就有内容）；打开时锁定背景滚动，并往浏览器历史写一条记录，
   所以手机返回键可以关闭弹窗。
4. 淡入用 `IntersectionObserver`。漂浮的蝴蝶结 / 星星、蛋糕线条、小光点等持续动画只用
   `opacity` 和 `transform`，走 GPU 合成，手机也流畅。
5. 深浅色只靠 CSS 变量整体换色板，布局完全不变，两套主题色调统一。
6. 所有装饰（Kitty、蝴蝶结、星星、小圆点）都是内联 SVG / CSS，没有任何图片贴图请求。

祝朋友生日快乐 🎂
