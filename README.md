# gomdb2sqlite

把 **GOM / Blue 系引擎**的 BDE 表(`Magic.DB` / `Monster.DB` / `StdItems.DB`)转换成 **SQLite**，
供 **RED 系三端引擎**(`DBServer.exe` / `M2Server.exe`)读取。

不依赖任何模板库，目标库不存在时自己建表；只依赖 Python 3.8+ 标准库。

---

## 为什么需要它

GOM 系的物品/怪物/技能定义放在 BDE 表里（`Mud2\DB\*.DB`），RED 系只认 SQLite
（`Mud2\DB\REDM2.DB` 的 `Magic` / `Monster` / `StdItems` 三张表）。两套格式互不兼容，
直接拷过去引擎读不到，`DBServer` 起来就报：

```
Access violation at address 004081FE in module 'DBServer.exe'. Read of address 00000300
```

这个工具把前者解出来写进后者。

---

## 用法

### 图形界面（推荐）

双击 `run_gui.bat`，或：

```bash
python gomdb2sqlite_gui.py
```

选源目录 → 自动检测三个 `.DB` 是否存在 → 勾选要转的表 → 开始转换，日志实时滚动。
输出默认落在源目录下的 `REDM2.DB`，已存在的旧库会自动备份成 `.bak`。

### 命令行

```bash
# 源目录里要有 Magic.DB / Monster.DB / StdItems.DB
python gomdb2sqlite.py --src D:\gomdb --out D:\MirServer\Mud2\DB\REDM2.DB

# 只要其中一张表
python gomdb2sqlite.py --src D:\gomdb --out out.db --table StdItems

# 同时输出一份报告
python gomdb2sqlite.py --src D:\gomdb --out out.db --report report.txt
```

Windows 下也可以双击 `run.bat`，把含三个 `.DB` 的目录拖进窗口回车。

输出示例：

```
Monster   字段 22 记录  98 每块 20 扫描 360 解析 347 入库 347 (剔 0 改名 13)
Magic     字段 44 记录 208 每块  9 扫描 252 解析 248 入库 248 (剔 0 改名 1)
StdItems  字段 48 记录 162 每块 12 扫描 732 解析 720 入库 693 (剔 27 改名 9)
```

- `解析` = 从二进制里成功读出的记录数
- `入库` = 清洗后最终写入的行数
- `剔` = 被剔除的垃圾行（广告行、`------` 分隔行、重名）
- `改名` = 重名项追加了 `(2)` `(3)` 序号，**名字内容本身不改**

---

## 文件格式（实测反推，非官方文档）

```
0x0021        字段数（1 字节）
0x0078 起      字段描述表，每字段 2 字节 =（类型, 宽度）
              0x01 Alpha（第二字节 = 字节数）
              0x03 ShortInt(2)  0x04 LongInt(4)  0x06 Number(8)
0x0204 起      字段名表，NUL 分隔的 ASCII
0x0800 起      记录区，按 2048 字节分块
              块内记录首尾相接，块尾留填充
              每块记录数 = 2048 // 记录长
每条记录       6 字节头（记录号等）+ 各字段依次排列
数值字段       首字节 0x80（有效标志）+ 剩余字节大端
字符串字段     GBK，NUL 结尾，尾部补 0
```

三张表的实际参数（同一引擎、同一版本）：

| 表 | 字段数 | 记录长 | 每块条数 |
|---|---|---|---|
| Monster | 22 | 98 | 20 |
| Magic | 44 | 208 | 9 |
| StdItems | 48 | 162 | 12 |

记录长 = `6 + 字段区宽度`，由字段描述表算出，然后用「连续 20 条名字都合法」做校验；
校验不过会自动搜索记录长兜底，所以换版本一般也能跑。

---

## RED 侧的三条硬要求

这几条不是格式问题，是引擎行为 —— 不满足就弹 **「物品数据库发生错误！」**，逐条踩过：

1. **字段不能为 NULL**
   引擎不判空，遇到 NULL 直接认为库损坏。脚本会把所有 NULL 补成 `0` 或 `''`。

2. **物品名必须唯一**
   引擎按名字建索引。版本作者常在表里塞重复行（占位名、同一件装备写两遍），必须剔掉。

3. **`Idx` / `MagID` 必须连续**
   引擎按数组下标访问。脚本会重排成 `0..N-1`（`Magic` 是 `1..N`）。

### 还有三条更阴的，都会报「物品数据库发生错误」或「Field xxx not found」

**① 建表顺序必须是 `StdItems` → `Magic` → `Monster`**

引擎按 `sqlite_master` 的顺序遍历表，并且假定第 1 张是物品、第 2 张是技能、第 3 张是怪物。
顺序不对**不会**报字段错，只会弹「物品数据库发生错误！」，查半天查不出所以然。
脚本 `main()` 里已经固定这个顺序，改代码时别动。

**② `Magic` 表不能漏列**

`Magic` 一共 44 列，`NeedL1..NeedL15` + `L1Train..L15Train` 各 15 组，然后是 `MaxTrainLv` / `Delay` / `Descr`。
拼 SQL 时漏一个逗号，`MaxTrainLv` 会被 SQLite 吞进类型名里（`INTEGER "MaxTrainLv" INTEGER`），
结果列数变成 43、`MaxTrainLv` 不存在 —— 引擎会直接报：

```
Field 'MaxTrainLv' not found
```

**③ 名字列的长度因表而异**

| 表 | 列 | 宽度 | 能不能放宽 |
|---|---|---|---|
| StdItems | `Name` | `TEXT(20)` | **可以放到 40**，实测 30 字节原名正常加载 |
| Monster | `Name` | `TEXT(14)` | 放到 40 没问题 |
| Magic | `MagName` | `TEXT(12)` | **不能动**，放宽就报「物品数据库发生错误」 |

所以 `StdItems.Name` 用 `TEXT(40)` 保原名，`Magic.MagName` / `Descr` 老老实实保持 `TEXT(12)`。

另外：

- **垃圾行**
  广告（`www.xxx.com`、QQ 群号）、`--------------` 分隔行，一并剔除。

- **验证要等满 16 秒**
  `DBServer` 启动后要十几秒才把物品库校验完，弹窗不是立刻出现的。等 6 秒看到"没报错"就下结论，会反复返工。

- **名字长度**
  `StdItems.Name` 放宽到 `TEXT(40)`，30 字节的装备名原样保留，不截断。
  只有重名项追加 `(2)` `(3)` 后缀，名字内容不变。

---

## 为什么不直接用 BDE 转换工具

`DBC2000数据库转换Sqlite库工具.exe` 这类 BDE 工具在这套表上会报：

```
Invalid pointer operation.
```

原因有三条，都绕不过去：

1. **它依赖 BDE 运行时**（Borland Database Engine）。这类工具通过 `TTable` / BDE 别名读 `.DB`，
   机器上没装 BDE（或没配别名）就会拿到空指针 —— `Invalid pointer operation` 正是 Delphi 扔空指针的典型报错。
2. **它认的是标准 Paradox 表**。这套 `.DB` 头部的版本字节是 `d0/62/a2`，不是标准的 `03/30`，
   记录编码也改成了「`0x80` 标志 + 大端」，BDE 按标准格式解会直接错位。
3. **它对字段映射写死了**。默认输出名 `ApexM2.DB` 说明它是给 Apex 系引擎写的，
   字段数（Magic 44 / Monster 22 / StdItems 48）和字段宽度跟 Apex 对不上，即使读出来也会写歪。

本工具不碰 BDE，直接按实测格式解析二进制，字段宽度从表头描述区读，所以不受上面三条限制。

---

## 验证

转换完，把目标库放到 `MirServer\Mud2\DB\REDM2.DB`，直接启动 `DBServer.exe`：

- 通过：进程存活，主窗体正常，`数据管理工具` / `人物管理` / `网关路由配置` 等子窗体全部建立
- 失败：弹「物品数据库发生错误！」，多半是上面三条硬要求里有一条没满足

`M2Server.exe` 也会读这个库，同样以不弹错为准。

> 注意：`DBServer` 启动后要等十几秒才会把物品库校验完，弹窗不是立刻出现的。

---

## 兼容性说明

- 只处理 `Magic` / `Monster` / `StdItems` 三张表，这三张是 RED 引擎实际读取的
- `Magic.Descr`（技能描述）在 BDE 里是 Memo 变长字段，本工具不解析，留空
- 不同引擎版本的 `Stdmode` 编号含义可能不同（比如 GOM 的 `5` 与 RED 的 `6`），
  本工具按原值搬运，不做事先映射；如果进游戏发现装备类型不对，需要自己对照两张表改
- `MagID` 会被重排成 `1..N`。如果 Envir 脚本里有**硬编码技能 ID 数字**的判断
  （正常写法是引用技能名），那几处会对不上

---

## 许可

MIT
