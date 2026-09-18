"""HTML 文本保真 Contract；固定解析输入，不替代真实 Agent E2E。"""

import pytest

from personal_agent.application.capture.utils import extract_html_text


@pytest.mark.parametrize(("html", "expected"), (
    (
        '<p>参数：<code>strict</code>；可选值：<code>false</code>。</p>'
        '<p>设置 <code>strict</code> 为 <code>true</code> 可约束调用参数。</p>'
        '<p><code>additionalProperties</code> 必须为 <code>false</code>。</p>',
        '参数：strict；可选值：false。\n设置 strict 为 true 可约束调用参数。\n'
        'additionalProperties 必须为 false。',
    ),
    ('<p>不可删除重复事实。</p><p>不可删除重复事实。</p>',
     '不可删除重复事实。\n不可删除重复事实。'),
    ('<p>调用 <code>tool_<b>choice</b></code>，返回<b>值</b>另有约定。</p>',
     '调用 tool_choice，返回值另有约定。'),
    ('<p>  条件\n <b>甲</b>\t与 <i>乙</i>  </p><p>丙<br/>丁</p>',
     '条件 甲 与 乙\n丙\n丁'),
    ('<p>甲&lt;乙 &amp; 乙&gt;甲；甲&nbsp;乙。</p>', '甲<乙 & 乙>甲；甲\u00a0乙。'),
    ('<pre><code>if <span>条件</span>:\n    值 = <b>False</b>\n\n    返回(值)</code></pre>',
     'if 条件:\n    值 = False\n\n    返回(值)'),
    ('<p>甲<script>坏内容</script><style>坏样式</style>'
     '<noscript><div>坏内容</div></noscript>乙</p>', '甲乙'),
    ('<p>最后一个 <b>片段', '最后一个 片段'),
    ('<script>无正文</script><!--注释-->', ''),
    ('<table><tr><th>参数</th><th>默认值</th></tr>'
     '<tr><td>严格检查</td><td>false</td></tr></table>',
     '参数\n默认值\n严格检查\nfalse'),
    ('<dl><dt>输入参数</dt><dd>必须检查</dd><dt>执行结果</dt><dd>由调用方负责</dd></dl>',
     '输入参数\n必须检查\n执行结果\n由调用方负责'),
), ids=("repeated-values", "repeated-paragraphs", "inline-boundaries",
        "normal-whitespace", "entities", "preformatted", "ignored-content",
        "unclosed-paragraph", "empty", "table-boundaries", "definition-boundaries"))
def test_html_text_preserves_order_values_and_boundaries(html: str, expected: str):
    assert extract_html_text(html) == expected


@pytest.mark.parametrize(("html", "expected"), (
    (
        '<nav>权限</nav><main><h1>调用规则</h1><p>仅检查输入。</p></main><footer>其他产品</footer>',
        '调用规则\n仅检查输入。',
    ),
    (
        '<div role="navigation">登录</div><div role="main"><nav>目录</nav>'
        '<p>只有用户确认后才可执行。</p><div role="navigation">下一页</div></div>',
        '只有用户确认后才可执行。',
    ),
    (
        '<main><header><h1>权限</h1><p>范围限于本应用。</p></header>'
        '<article><p>未获批准不得执行。</p><footer>例外需重新确认。</footer></article></main>',
        '权限\n范围限于本应用。\n未获批准不得执行。\n例外需重新确认。',
    ),
    ('<main role="main"><div role="main"><p>甲</p></div><p>乙</p></main>', '甲\n乙'),
    ('<main><p>甲</p></main><main><p>乙</p></main><p>附注</p>', '甲\n乙\n附注'),
    ('<article><p>说明甲</p></article><article><p>说明乙</p></article>', '说明甲\n说明乙'),
    (
        '<main><p>仅 <code>false</code> 表示关闭；<code>false</code> 不代表成功。</p>'
        '<pre><code>if 条件:\n    值 = False\n\n    返回(值)</code></pre>'
        '<table><tr><th>检查项</th><th>必需</th></tr><tr><td>结果</td><td>否</td></tr></table></main>',
        '仅 false 表示关闭；false 不代表成功。\nif 条件:\n    值 = False\n\n    返回(值)\n检查项\n必需\n结果\n否',
    ),
    ('<main><p>重复</p><p>重复</p></main>', '重复\n重复'),
    ('<main><p>甲&lt;乙 &amp; 乙&gt;甲；甲&nbsp;乙。</p></main>', '甲<乙 & 乙>甲；甲\u00a0乙。'),
    ('<main><p>正文<script>坏内容</script><style>坏样式</style>尾句</p></main>', '正文尾句'),
    ('<main><p>未闭合 <b>正文', '未闭合 正文'),
    ('<main><nav>只有导航</nav></main>', ''),
), ids=("separate-navigation", "aria-regions", "preserve-body-header-footer",
        "nested-main", "ambiguous-main", "no-main", "code-table-conditions",
        "duplicate-body", "entities-in-main", "ignore-scripts-in-main",
        "unclosed-main", "no-body"))
def test_html_main_region_preserves_evidence(html: str, expected: str):
    assert extract_html_text(html) == expected


@pytest.mark.parametrize(("html", "expected"), (
    ('<noscript><main>替代提示</main></noscript><p>真实正文</p>', '真实正文'),
    ('<noscript><div role="main">替代提示</div></noscript>'
     '<article><p>真实正文</p></article>', '真实正文'),
    ('<main><p>正文甲</p><noscript><main>替代提示</main></noscript>'
     '<p>正文乙</p></main>', '正文甲\n正文乙'),
), ids=("ignored-main", "ignored-aria-main", "nested-ignored-main"))
def test_main_selection_keeps_ignored_ancestor_scope(html: str, expected: str):
    assert extract_html_text(html) == expected
