namespace BrainstormAssistant.Tests;

public class MarkdownRendererTests
{
    // ===================== EscapeHtml =====================

    [Fact]
    public void EscapeHtml_EscapesAngleBrackets()
    {
        var result = MainWindow.EscapeHtml("<div>test</div>");
        Assert.DoesNotContain("<div>", result);
        Assert.Contains("&lt;div&gt;", result);
    }

    [Fact]
    public void EscapeHtml_EscapesAmpersand()
    {
        var result = MainWindow.EscapeHtml("A & B");
        Assert.Contains("A &amp; B", result);
    }

    [Fact]
    public void EscapeHtml_EscapesQuotes()
    {
        var result = MainWindow.EscapeHtml("class=\"foo\"");
        Assert.Contains("&quot;", result);
    }

    // ===================== InlineFormat =====================

    [Fact]
    public void InlineFormat_Bold()
    {
        var result = MainWindow.InlineFormat("This is **bold** text");
        Assert.Contains("<strong>bold</strong>", result);
    }

    [Fact]
    public void InlineFormat_Italic()
    {
        var result = MainWindow.InlineFormat("This is *italic* text");
        Assert.Contains("<em>italic</em>", result);
    }

    [Fact]
    public void InlineFormat_InlineCode()
    {
        var result = MainWindow.InlineFormat("Use `var x = 1` here");
        Assert.Contains("<code>var x = 1</code>", result);
    }

    [Fact]
    public void InlineFormat_Link()
    {
        var result = MainWindow.InlineFormat("See [Google](https://google.com)");
        Assert.Contains("<a href=\"https://google.com\">Google</a>", result);
    }

    [Fact]
    public void InlineFormat_EscapesHtmlBeforeFormatting()
    {
        var result = MainWindow.InlineFormat("A < B & C > D");
        Assert.Contains("&lt;", result);
        Assert.Contains("&amp;", result);
        Assert.Contains("&gt;", result);
    }

    [Fact]
    public void InlineFormat_PlainTextWithArrows_NotWrappedInStrong()
    {
        // This was the bug: mermaid arrows like --> were being mangled
        var result = MainWindow.InlineFormat("A --> B");
        Assert.DoesNotContain("<strong>", result);
        Assert.DoesNotContain("<em>", result);
    }

    // ===================== ConvertMarkdownToHtml =====================

    [Fact]
    public void ConvertMarkdownToHtml_Header1()
    {
        var result = MainWindow.ConvertMarkdownToHtml("# Hello World");
        Assert.Contains("<h1>Hello World</h1>", result);
    }

    [Fact]
    public void ConvertMarkdownToHtml_Header2()
    {
        var result = MainWindow.ConvertMarkdownToHtml("## Section Title");
        Assert.Contains("<h2>Section Title</h2>", result);
    }

    [Fact]
    public void ConvertMarkdownToHtml_Header3()
    {
        var result = MainWindow.ConvertMarkdownToHtml("### Subsection");
        Assert.Contains("<h3>Subsection</h3>", result);
    }

    [Fact]
    public void ConvertMarkdownToHtml_HorizontalRule()
    {
        var result = MainWindow.ConvertMarkdownToHtml("---");
        Assert.Contains("<hr>", result);
    }

    [Fact]
    public void ConvertMarkdownToHtml_Blockquote()
    {
        var result = MainWindow.ConvertMarkdownToHtml("> This is a quote");
        Assert.Contains("<blockquote>This is a quote</blockquote>", result);
    }

    [Fact]
    public void ConvertMarkdownToHtml_UnorderedList()
    {
        var md = "- Item 1\n- Item 2\n- Item 3";
        var result = MainWindow.ConvertMarkdownToHtml(md);
        Assert.Contains("<ul>", result);
        Assert.Contains("<li>Item 1</li>", result);
        Assert.Contains("<li>Item 2</li>", result);
        Assert.Contains("<li>Item 3</li>", result);
        Assert.Contains("</ul>", result);
    }

    [Fact]
    public void ConvertMarkdownToHtml_OrderedList()
    {
        var md = "1. First\n2. Second\n3. Third";
        var result = MainWindow.ConvertMarkdownToHtml(md);
        Assert.Contains("<ol>", result);
        Assert.Contains("<li>First</li>", result);
        Assert.Contains("<li>Second</li>", result);
        Assert.Contains("</ol>", result);
    }

    [Fact]
    public void ConvertMarkdownToHtml_Paragraph()
    {
        var result = MainWindow.ConvertMarkdownToHtml("Just some text");
        Assert.Contains("<p>Just some text</p>", result);
    }

    [Fact]
    public void ConvertMarkdownToHtml_CodeBlock()
    {
        var md = "```csharp\nvar x = 1;\nConsole.WriteLine(x);\n```";
        var result = MainWindow.ConvertMarkdownToHtml(md);
        Assert.Contains("<pre><code>", result);
        Assert.Contains("var x = 1;", result);
        Assert.Contains("</code></pre>", result);
    }

    [Fact]
    public void ConvertMarkdownToHtml_CodeBlock_EscapesHtmlInside()
    {
        var md = "```\n<div class=\"foo\">test</div>\n```";
        var result = MainWindow.ConvertMarkdownToHtml(md);
        Assert.Contains("&lt;div", result);
        Assert.DoesNotContain("<div class", result);
    }

    [Fact]
    public void ConvertMarkdownToHtml_MermaidBlock_RendersAsStyledDiv()
    {
        var md = "```mermaid\ngraph TD\n    A[Start] --> B{Decision}\n    B -->|Yes| C[Option 1]\n    B -->|No| D[Option 2]\n    C --> E[End]\n    D --> E\n```";
        var result = MainWindow.ConvertMarkdownToHtml(md);
        Assert.Contains("mermaid-block", result);
        Assert.Contains("graph TD", result);
        Assert.Contains("A[Start]", result);
        // Must NOT contain <strong> tags — this was the original bug
        Assert.DoesNotContain("<strong>", result);
        Assert.DoesNotContain("<em>", result);
    }

    [Fact]
    public void ConvertMarkdownToHtml_MermaidBlock_EscapesHtml()
    {
        var md = "```mermaid\ngraph LR\n    A --> B\n```";
        var result = MainWindow.ConvertMarkdownToHtml(md);
        // The --> should be escaped as --&gt; inside the mermaid block
        Assert.Contains("--&gt;", result);
    }

    [Fact]
    public void ConvertMarkdownToHtml_BoldInParagraph()
    {
        var result = MainWindow.ConvertMarkdownToHtml("This is **important** text");
        Assert.Contains("<strong>important</strong>", result);
    }

    [Fact]
    public void ConvertMarkdownToHtml_MixedContent()
    {
        var md = "# Title\n\nSome **bold** text.\n\n- Item 1\n- Item 2\n\n```\ncode here\n```\n\nEnd paragraph.";
        var result = MainWindow.ConvertMarkdownToHtml(md);
        Assert.Contains("<h1>Title</h1>", result);
        Assert.Contains("<strong>bold</strong>", result);
        Assert.Contains("<ul>", result);
        Assert.Contains("<pre><code>", result);
        Assert.Contains("<p>End paragraph.</p>", result);
    }

    [Fact]
    public void ConvertMarkdownToHtml_Table()
    {
        var md = "| Name | Value |\n|------|-------|\n| Foo  | 42    |\n| Bar  | 99    |";
        var result = MainWindow.ConvertMarkdownToHtml(md);
        Assert.Contains("<table>", result);
        Assert.Contains("<th>", result);
        Assert.Contains("Name", result);
        Assert.Contains("<td>", result);
        Assert.Contains("42", result);
        Assert.Contains("</table>", result);
    }

    [Fact]
    public void ConvertMarkdownToHtml_UnorderedListWithAsterisks()
    {
        var md = "* Item A\n* Item B";
        var result = MainWindow.ConvertMarkdownToHtml(md);
        Assert.Contains("<ul>", result);
        Assert.Contains("<li>Item A</li>", result);
        Assert.Contains("<li>Item B</li>", result);
    }

    // ===================== WrapMarkdownInHtml =====================

    [Fact]
    public void WrapMarkdownInHtml_ReturnsFullHtmlDocument()
    {
        var result = MainWindow.WrapMarkdownInHtml("# Test");
        Assert.Contains("<!DOCTYPE html>", result);
        Assert.Contains("<html>", result);
        Assert.Contains("</html>", result);
        Assert.Contains("<h1>Test</h1>", result);
    }

    [Fact]
    public void WrapMarkdownInHtml_HasDarkThemeStyles()
    {
        var result = MainWindow.WrapMarkdownInHtml("Hello");
        Assert.Contains("#1E1E1E", result); // dark background
        Assert.Contains("#E0E0E0", result); // light text
    }

    [Fact]
    public void WrapMarkdownInHtml_MermaidBlock_NoStrongTags()
    {
        var md = "```mermaid\ngraph TD\n    A[Start] --> B{Decision}\n    B -->|Yes| C[Option 1]\n    B -->|No| D[Option 2]\n```\n\nCheck the board.";
        var result = MainWindow.WrapMarkdownInHtml(md);

        // The mermaid content should be in a styled div, not in <strong> tags
        Assert.Contains("mermaid-block", result);

        // Count <strong> tags — there should be zero from mermaid content
        // The "Check the board." paragraph has no bold, so no strong tags expected at all
        Assert.DoesNotContain("<strong>", result);
    }

    [Fact]
    public void ConvertMarkdownToHtml_EmptyInput()
    {
        var result = MainWindow.ConvertMarkdownToHtml("");
        Assert.NotNull(result);
    }

    [Fact]
    public void ConvertMarkdownToHtml_ListClosedOnEmptyLine()
    {
        var md = "- A\n- B\n\nParagraph after list.";
        var result = MainWindow.ConvertMarkdownToHtml(md);
        Assert.Contains("</ul>", result);
        Assert.Contains("<p>Paragraph after list.</p>", result);
    }
}
