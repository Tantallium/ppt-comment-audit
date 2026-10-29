"""本地可离线阅读的 Material Design 3 检查报告。"""
import html


def write_html(folder, summary, results, labels):
    counts = summary['counts']
    issues = counts['duplicate'] + counts['invalid']
    unchecked = counts['uncheckable'] + counts['unsupported']
    excluded = summary.get('excluded_directories', [])
    excluded_rows = ''.join(f'<li class="roots">{html.escape(item["path"])} — {html.escape(item["reason"])}</li>'
                            for item in excluded)
    mode = html.escape(summary.get('scan_mode_label', '全面扫描'))
    rows = []
    for result in results:
        state = result['status']
        tone = 'error' if state in {'duplicate', 'invalid'} else 'warning' if state != 'clear' else 'success'
        rows.append(f'<tr data-status="{state}"><td><span class="badge {tone}">{labels[state]}</span></td>'
                    f'<td class="path">{html.escape(result["path"])}</td>'
                    f'<td>{result["authors"]}</td><td>{result["duplicate_records"]}</td>'
                    f'<td>{"符合" if result["append_pattern"] else "未标记"}</td>'
                    f'<td>{html.escape(result["application"])}</td><td>{html.escape(result["note"])}</td></tr>')
    cards = ''.join(f'<div class="metric {tone}"><span>{text}</span><strong>{number:,}</strong></div>'
                    for text, number, tone in [('检查文件', summary['checked'], ''),
                                              ('编号问题', issues, 'error'),
                                              ('未发现本次编号问题', counts['clear'], 'success'),
                                              ('无法检查 / 旧格式', unchecked, 'warning')])
    document = '''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PPT 批注编号检查报告</title><style>
:root{--surface:#f8fafd;--low:#f0f4f9;--container:#e9eef6;--primary:#0b57d0;--primary-container:#d3e3fd;--text:#1f1f1f;--muted:#444746;--outline:#747775;--error:#b3261e;--success:#146c2e;--warning:#7a4d00}
*{box-sizing:border-box}body{margin:0;background:var(--surface);color:var(--text);font:14px/1.65 "Segoe UI","Microsoft YaHei UI",sans-serif}
main{max-width:1440px;padding:48px 40px;margin:auto}header{display:flex;justify-content:space-between;gap:24px;align-items:center;margin-bottom:28px}
.eyebrow{color:var(--primary);letter-spacing:.08em;font-size:12px;font-weight:600}h1{font-size:34px;line-height:1.3;margin:8px 0 12px;font-weight:650}header p{margin:0;color:var(--muted)}
.local{border-radius:999px;padding:8px 16px;background:#c4eed0;color:var(--success);white-space:nowrap}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px}
.metric{background:white;border-radius:24px;padding:24px}.metric span{display:block;color:var(--muted)}.metric strong{font-size:40px;line-height:1.3;display:block;margin-top:12px;font-weight:600}
.error{color:var(--error)}.success{color:var(--success)}.warning{color:var(--warning)}.panel{background:white;border-radius:28px;overflow:hidden}.toolbar{padding:24px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
button{border:1px solid var(--outline);border-radius:12px;padding:10px 18px;background:transparent;color:var(--muted);cursor:pointer;font:inherit;min-height:44px}
button:hover{background:var(--low)}button[aria-pressed="true"]{background:var(--primary-container);border-color:var(--primary-container);color:#0842a0}
button:focus-visible,input:focus-visible,summary:focus-visible{outline:3px solid var(--primary);outline-offset:3px}.search{display:flex;gap:12px;align-items:center;margin-left:auto}
input{border:1px solid var(--outline);border-radius:24px;background:var(--low);padding:12px 18px;min-width:240px;font:inherit;color:var(--text)}.table-scroll{overflow:auto;max-height:70vh}
table{border-collapse:collapse;width:100%;text-align:left;min-width:960px;font-size:13px}th{background:var(--low);color:var(--muted);font-weight:600;padding:16px;position:sticky;top:0;z-index:1}
td{padding:18px 16px;border-bottom:1px solid var(--container);vertical-align:top;overflow-wrap:anywhere}tbody tr:hover{background:var(--surface)}.path{min-width:260px;max-width:450px}td:last-child{min-width:240px;max-width:380px}
.badge{padding:5px 10px;display:inline-block;border-radius:8px;white-space:nowrap;font-size:12px}.badge.error{background:#f9dedc}.badge.success{background:#c4eed0}.badge.warning{background:#ffe7b4}
.table-footer{padding:16px 24px;color:var(--muted);display:flex;justify-content:space-between;gap:12px}.empty{padding:48px;text-align:center;color:var(--muted)}details{margin-top:24px;background:var(--low);padding:20px 24px;border-radius:20px}
summary{cursor:pointer;font-weight:600;min-height:28px}details p{max-width:1000px;color:var(--muted)}.roots{overflow-wrap:anywhere}footer{padding-top:24px;color:var(--muted);font-size:12px}
@media(max-width:800px){main{padding:24px 16px}header{align-items:flex-start}h1{font-size:28px}.metrics{grid-template-columns:repeat(2,1fr);gap:12px}.metric{padding:20px}.search{margin:8px 0 0;width:100%}.search input{min-width:0;flex:1}.toolbar{padding:16px}button{padding:8px 12px}.table-footer{display:block}.local{font-size:12px}}
@media print{main{padding:0}.toolbar{display:none}.table-scroll{max-height:none;overflow:visible}table{min-width:0}th{position:static}td{font-size:10px}.panel{border-radius:0}.metric{border:1px solid #ddd}}
</style></head><body><main>'''
    document += f'''<header><div><div class="eyebrow">PPT 文件检查</div><h1>批注编号检查报告</h1>
<p>{html.escape(summary['finished_at'])} · {html.escape(summary['state'])}</p></div><span class="local">本地 · 只读</span></header>
<section class="metrics" aria-label="检查摘要">{cards}</section>
<section class="panel" aria-label="逐文件检查结果"><div class="toolbar" role="search">
<button data-filter="all" aria-pressed="true">全部</button><button data-filter="problem" aria-pressed="false">编号问题</button>
<button data-filter="clear" aria-pressed="false">未发现问题</button><button data-filter="unchecked" aria-pressed="false">无法检查 / 旧格式</button>
<div class="search"><label for="search">搜索文件</label><input id="search" type="search" placeholder="文件名或路径"></div></div>
<div class="table-scroll"><table><thead><tr><th scope="col">检查结果</th><th scope="col">文件路径</th><th scope="col">作者数</th><th scope="col">重复记录</th>
<th scope="col">末尾追加冲突特征</th><th scope="col">保存软件标记</th><th scope="col">检查说明</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<div id="empty" class="empty" hidden>没有匹配的文件，请调整筛选条件或搜索词。</div></div>
<div class="table-footer"><span id="visible-count" role="status" aria-live="polite"></span><span>遍历 {summary['directories']:,} 个目录 · 跳过或无法访问 {summary['skipped']:,} 项</span></div></section>
<details><summary>检查范围与结果说明</summary><p class="roots">检查范围：{html.escape('、'.join(summary['roots']))}</p>
<p>扫描模式：{mode}。自定义排除在两种模式下均生效；手动指定的位置可覆盖推荐排除。</p>
<p>本工具只检查传统批注作者编号，源文件保持不变。“未发现本次编号问题”不代表文件一定能在 PowerPoint 中打开。
“末尾追加冲突特征”指重复记录连续位于末尾且编号连续递增；保存软件标记用于排查线索，均不作为问题来源的证明。</p>
<p>具体范围与跳过原因见同目录的“扫描摘要.json”和“未检查项目.jsonl”。CSV 清单可在 Excel 中打开。</p></details>
<details><summary>推荐与自定义排除目录 · {len(excluded)} 项</summary>
<ul>{excluded_rows}</ul><p>全部基础排除及无法访问原因见“未检查项目.jsonl”。</p></details>
<footer>PPT 批注编号检查工具 · v1.7</footer>'''
    document += '''</main><script>
let mode='all';const rows=[...document.querySelectorAll('tbody tr')];
function filterRows(){const q=document.getElementById('search').value.trim().toLocaleLowerCase();let visible=0;
for(const r of rows){const s=r.dataset.status;const match=mode==='all'||(mode==='problem'&&['duplicate','invalid'].includes(s))||(mode==='clear'&&s==='clear')||(mode==='unchecked'&&['uncheckable','unsupported'].includes(s));
r.hidden=!(match&&r.cells[1].textContent.toLocaleLowerCase().includes(q));if(!r.hidden)visible++;}
document.getElementById('visible-count').textContent=`显示 ${visible} / ${rows.length} 个文件`;document.getElementById('empty').hidden=visible!==0;}
document.querySelectorAll('[data-filter]').forEach(b=>b.addEventListener('click',()=>{mode=b.dataset.filter;document.querySelectorAll('[data-filter]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));filterRows();}));
document.getElementById('search').addEventListener('input',filterRows);filterRows();
</script></body></html>'''
    (folder / '检查报告.html').write_text(document, encoding='utf-8')
