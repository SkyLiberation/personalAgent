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
