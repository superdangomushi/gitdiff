package main

import (
	"bytes"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"

	"github.com/alecthomas/chroma/v2"
	"github.com/alecthomas/chroma/v2/lexers"
	"github.com/alecthomas/chroma/v2/styles"
	"github.com/gdamore/tcell/v2"
	"github.com/rivo/tview"
)

// ─── Themes ───────────────────────────────────────────────────────────────────

type colorTheme struct {
	name           string
	headerBg       tcell.Color
	sidebarTitleBg tcell.Color
	diffTitleBg    tcell.Color
	editorTitleBg  tcell.Color
	helpBarBg      tcell.Color
	helpBarText    string // tview color name/hex used in markup
	contentBg      tcell.Color
	addLineMarkup  string // color pair inside [...], e.g. "white:darkgreen:"
	delLineMarkup  string
	modalBg        tcell.Color
	chromaStyle    string
}

var darkTheme = colorTheme{
	name:           "Dark",
	headerBg:       tcell.ColorNavy,
	sidebarTitleBg: tcell.NewRGBColor(0x22, 0x44, 0xAA),
	diffTitleBg:    tcell.NewRGBColor(0x00, 0x66, 0x33),
	editorTitleBg:  tcell.NewRGBColor(0x66, 0x33, 0x00),
	helpBarBg:      tcell.NewRGBColor(0x1A, 0x1A, 0x1A),
	helpBarText:    "darkgray",
	contentBg:      tcell.ColorDefault,
	addLineMarkup:  "white:darkgreen:",
	delLineMarkup:  "white:darkred:",
	modalBg:        tcell.NewRGBColor(0x22, 0x22, 0x44),
	chromaStyle:    "monokai",
}

var lightTheme = colorTheme{
	name:           "Light",
	headerBg:       tcell.NewRGBColor(0x33, 0x66, 0xAA),
	sidebarTitleBg: tcell.NewRGBColor(0x99, 0xBB, 0xEE),
	diffTitleBg:    tcell.NewRGBColor(0x55, 0x99, 0x77),
	editorTitleBg:  tcell.NewRGBColor(0xCC, 0x88, 0x33),
	helpBarBg:      tcell.NewRGBColor(0xDD, 0xDD, 0xDD),
	helpBarText:    "#333333",
	contentBg:      tcell.ColorWhite,
	addLineMarkup:  "black:#AADDAA:",
	delLineMarkup:  "black:#FFAAAA:",
	modalBg:        tcell.NewRGBColor(0xCC, 0xCC, 0xFF),
	chromaStyle:    "friendly",
}

// ─── Status metadata ──────────────────────────────────────────────────────────

type statusStyle struct {
	color string
	badge string
	desc  string
}

var statusStyles = map[string]statusStyle{
	"A": {"green", "[+]", "Added"},
	"M": {"yellow", "[~]", "Modified"},
	"D": {"red", "[-]", "Deleted"},
	"R": {"cyan", "[→]", "Renamed"},
	"C": {"blue", "[©]", "Copied"},
	"T": {"magenta", "[T]", "Type changed"},
}

var extLang = map[string]string{
	".py": "python", ".js": "javascript", ".ts": "typescript",
	".tsx": "tsx", ".jsx": "javascript",
	".sh": "bash", ".bash": "bash",
	".md": "markdown", ".json": "json",
	".yaml": "yaml", ".yml": "yaml",
	".css": "css", ".html": "html", ".xml": "xml",
	".go": "go", ".rs": "rust", ".c": "c",
	".cpp": "cpp", ".h": "c", ".rb": "ruby",
	".php": "php", ".java": "java", ".kt": "kotlin",
	".sql": "sql", ".toml": "toml",
}

// ─── Data types ───────────────────────────────────────────────────────────────

type fileInfo struct {
	status string
	path   string
}

type fileStats struct {
	added   string
	deleted string
}

type diffLine struct {
	kind    string // "add" | "del" | "ctx"
	content string
	lineNum int // 0 = N/A (deleted lines have no new-file line number)
}

// ─── Git helpers ──────────────────────────────────────────────────────────────

func runGit(args ...string) (stdout, stderr string, exitCode int) {
	cmd := exec.Command("git", args...)
	var outBuf, errBuf bytes.Buffer
	cmd.Stdout = &outBuf
	cmd.Stderr = &errBuf
	if err := cmd.Run(); err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			exitCode = exitErr.ExitCode()
		} else {
			exitCode = 1
		}
	}
	return outBuf.String(), errBuf.String(), exitCode
}

func checkGitRepo() bool {
	_, _, rc := runGit("rev-parse", "--git-dir")
	return rc == 0
}

func getCurrentBranch() string {
	out, _, rc := runGit("branch", "--show-current")
	if name := strings.TrimSpace(out); rc == 0 && name != "" {
		return name
	}
	out, _, _ = runGit("rev-parse", "--short", "HEAD")
	if s := strings.TrimSpace(out); s != "" {
		return s
	}
	return "unknown"
}

func checkRef(ref string) bool {
	_, _, rc := runGit("rev-parse", "--verify", ref)
	return rc == 0
}

func getRepoRoot() string {
	out, _, rc := runGit("rev-parse", "--show-toplevel")
	if rc == 0 {
		return strings.TrimSpace(out)
	}
	return ""
}

func diffRef(branchA, branchB string) string {
	if branchB != "" {
		return branchA + "..." + branchB
	}
	return branchA
}

func getDiffFiles(branchA, branchB string) ([]fileInfo, error) {
	out, stderr, rc := runGit("diff", "--name-status", diffRef(branchA, branchB))
	if rc != 0 {
		return nil, fmt.Errorf("%s", strings.TrimSpace(stderr))
	}
	var files []fileInfo
	for _, line := range strings.Split(strings.TrimSpace(out), "\n") {
		if line == "" {
			continue
		}
		parts := strings.Split(line, "\t")
		status := string(parts[0][0])
		filename := parts[len(parts)-1]
		files = append(files, fileInfo{status: status, path: filename})
	}
	return files, nil
}

func getFileStats(branchA, branchB string) map[string]fileStats {
	out, _, _ := runGit("diff", "--numstat", diffRef(branchA, branchB))
	stats := make(map[string]fileStats)
	for _, line := range strings.Split(strings.TrimSpace(out), "\n") {
		if line == "" {
			continue
		}
		parts := strings.Split(line, "\t")
		if len(parts) == 3 {
			stats[parts[2]] = fileStats{added: parts[0], deleted: parts[1]}
		}
	}
	return stats
}

func getFileDiff(branchA, branchB, filename string) string {
	out, _, _ := runGit("diff", diffRef(branchA, branchB), "--", filename)
	return out
}

// ─── Diff parsing ─────────────────────────────────────────────────────────────

var hunkHeaderRe = regexp.MustCompile(`\+(\d+)`)

func parseDiffLines(diffText string) []diffLine {
	var result []diffLine
	lineNum := 0
	inHunk := false

	for _, line := range strings.Split(diffText, "\n") {
		switch {
		case strings.HasPrefix(line, "diff "), strings.HasPrefix(line, "index "),
			strings.HasPrefix(line, "--- "), strings.HasPrefix(line, "+++ "):
			inHunk = false
		case strings.HasPrefix(line, "@@"):
			if m := hunkHeaderRe.FindStringSubmatch(line); m != nil {
				n, _ := strconv.Atoi(m[1])
				lineNum = n - 1
			}
			inHunk = true
		case !inHunk, strings.HasPrefix(line, "\\"):
			// skip
		case strings.HasPrefix(line, "+"):
			lineNum++
			result = append(result, diffLine{kind: "add", content: line[1:], lineNum: lineNum})
		case strings.HasPrefix(line, "-"):
			result = append(result, diffLine{kind: "del", content: line[1:]})
		case len(line) > 0:
			lineNum++
			result = append(result, diffLine{kind: "ctx", content: line[1:], lineNum: lineNum})
		}
	}
	return result
}

// ─── View helpers ─────────────────────────────────────────────────────────────

// buildEditorView renders diff lines as tview markup with themed line backgrounds.
func buildEditorView(lines []diffLine, showDeleted bool, theme colorTheme) string {
	if len(lines) == 0 {
		return "[::d]No diff data available.[-:-:-]"
	}
	maxNum := 0
	for _, dl := range lines {
		if dl.lineNum > maxNum {
			maxNum = dl.lineNum
		}
	}
	w := len(strconv.Itoa(maxNum))
	if w < 1 {
		w = 1
	}
	gutterFmt := fmt.Sprintf("%%%dd ", w)

	var sb strings.Builder
	for _, dl := range lines {
		if dl.kind == "del" && !showDeleted {
			continue
		}
		var gutter string
		if dl.lineNum > 0 {
			gutter = fmt.Sprintf(gutterFmt, dl.lineNum)
		} else {
			gutter = fmt.Sprintf("%*s ", w, "~")
		}
		content := tview.Escape(dl.content)
		switch dl.kind {
		case "add":
			fmt.Fprintf(&sb, "[%s]%s%s[-:-:-]\n", theme.addLineMarkup, gutter, content)
		case "del":
			fmt.Fprintf(&sb, "[%s]%s%s[-:-:-]\n", theme.delLineMarkup, gutter, content)
		default:
			sb.WriteString(gutter + content + "\n")
		}
	}
	return sb.String()
}

// chromaHighlight returns tview markup for syntax-highlighted text.
func chromaHighlight(code, langName, styleName string) string {
	lexer := lexers.Get(langName)
	if lexer == nil {
		lexer = lexers.Fallback
	}
	lexer = chroma.Coalesce(lexer)

	style := styles.Get(styleName)
	if style == nil {
		style = styles.Fallback
	}

	iter, err := lexer.Tokenise(nil, code)
	if err != nil {
		return tview.Escape(code)
	}

	var sb strings.Builder
	for token := iter(); token != chroma.EOF; token = iter() {
		entry := style.Get(token.Type)
		escaped := tview.Escape(token.Value)
		if entry.Colour.IsSet() {
			c := entry.Colour
			hex := fmt.Sprintf("#%02X%02X%02X", c.Red(), c.Green(), c.Blue())
			// Color markup must not span newlines in tview.
			parts := strings.Split(escaped, "\n")
			for i, part := range parts {
				if i > 0 {
					sb.WriteByte('\n')
				}
				if part != "" {
					fmt.Fprintf(&sb, "[%s]%s[-]", hex, part)
				}
			}
		} else {
			sb.WriteString(escaped)
		}
	}
	return sb.String()
}

// withLineNumbers prepends 1-based line numbers to each line of tview markup.
func withLineNumbers(markup string) string {
	lines := strings.Split(markup, "\n")
	if len(lines) > 0 && lines[len(lines)-1] == "" {
		lines = lines[:len(lines)-1]
	}
	w := len(strconv.Itoa(len(lines)))
	gutterFmt := fmt.Sprintf("[darkgray]%%%dd [-]", w)

	var sb strings.Builder
	for i, line := range lines {
		fmt.Fprintf(&sb, gutterFmt, i+1)
		sb.WriteString(line)
		sb.WriteByte('\n')
	}
	return sb.String()
}

// highlightDiff returns tview markup for a unified diff with line numbers.
func highlightDiff(diffText, styleName string) string {
	return withLineNumbers(chromaHighlight(diffText, "diff", styleName))
}

// ─── Application ──────────────────────────────────────────────────────────────

type application struct {
	tv    *tview.Application
	pages *tview.Pages

	branchA     string
	branchB     string
	files       []fileInfo
	stats       map[string]fileStats
	currentIdx  int
	showDeleted bool
	showEditor  bool
	editMode    bool
	repoRoot    string
	diffLines   []diffLine
	theme       colorTheme

	// Widgets
	header       *tview.TextView
	sidebarTitle *tview.TextView
	fileList     *tview.List
	diffTitle    *tview.TextView
	diffView     *tview.TextView
	editorTitle  *tview.TextView
	editorView   *tview.TextView // right panel: view mode
	editor       *tview.TextArea // right panel: edit mode
	helpBar      *tview.TextView
	statusBar    *tview.TextView
	mainFlex     *tview.Flex // sidebar | diffPanel | rightPanel
	rightPanel   *tview.Flex // editorTitle + (editorView or editor)
}

func newApplication(branchA, branchB string, files []fileInfo, stats map[string]fileStats) *application {
	a := &application{
		branchA:     branchA,
		branchB:     branchB,
		files:       files,
		stats:       stats,
		showDeleted: true,
		showEditor:  true,
		repoRoot:    getRepoRoot(),
		theme:       darkTheme,
	}
	a.tv = tview.NewApplication()
	a.buildUI()
	return a
}

func (a *application) bLabel() string {
	if a.branchB != "" {
		return a.branchB
	}
	return "Working Tree"
}

func (a *application) buildUI() {
	t := a.theme

	// ── Header ───────────────────────────────────────────────────────────────
	a.header = tview.NewTextView().SetDynamicColors(true).SetTextAlign(tview.AlignCenter)
	a.header.SetBackgroundColor(t.headerBg)
	a.refreshHeader()

	// ── Sidebar ──────────────────────────────────────────────────────────────
	a.sidebarTitle = tview.NewTextView().SetDynamicColors(true)
	a.sidebarTitle.SetBackgroundColor(t.sidebarTitleBg)
	a.sidebarTitle.SetText(fmt.Sprintf(" Files (%d)", len(a.files)))

	a.fileList = tview.NewList().ShowSecondaryText(false)
	a.fileList.SetBackgroundColor(t.contentBg)
	a.populateFileList()
	a.fileList.SetChangedFunc(func(idx int, _, _ string, _ rune) {
		if idx >= 0 && idx < len(a.files) {
			a.currentIdx = idx
			a.loadFile(idx)
		}
	})

	sidebar := tview.NewFlex().SetDirection(tview.FlexRow).
		AddItem(a.sidebarTitle, 1, 0, false).
		AddItem(a.fileList, 0, 1, true)

	// ── Diff panel ───────────────────────────────────────────────────────────
	a.diffTitle = tview.NewTextView().SetDynamicColors(true)
	a.diffTitle.SetBackgroundColor(t.diffTitleBg)
	a.diffTitle.SetText(fmt.Sprintf(" %s  →  %s", a.branchA, a.bLabel()))

	a.diffView = tview.NewTextView().
		SetDynamicColors(true).SetScrollable(true).SetWrap(false)
	a.diffView.SetBackgroundColor(t.contentBg)
	a.diffView.SetText("← Select a file")

	diffPanel := tview.NewFlex().SetDirection(tview.FlexRow).
		AddItem(a.diffTitle, 1, 0, false).
		AddItem(a.diffView, 0, 1, false)

	// ── Editor panel ─────────────────────────────────────────────────────────
	a.editorTitle = tview.NewTextView().SetDynamicColors(true)
	a.editorTitle.SetBackgroundColor(t.editorTitleBg)
	a.editorTitle.SetText(" Editor")

	a.editorView = tview.NewTextView().
		SetDynamicColors(true).SetScrollable(true).SetWrap(false)
	a.editorView.SetBackgroundColor(t.contentBg)
	a.editorView.SetText("← Select a file")

	a.editor = tview.NewTextArea().SetWrap(false)

	a.rightPanel = tview.NewFlex().SetDirection(tview.FlexRow).
		AddItem(a.editorTitle, 1, 0, false).
		AddItem(a.editorView, 0, 1, false)

	// ── Help bar ─────────────────────────────────────────────────────────────
	a.helpBar = tview.NewTextView().SetDynamicColors(true)
	a.helpBar.SetBackgroundColor(t.helpBarBg)
	a.refreshHelpBar()

	// ── Status bar ───────────────────────────────────────────────────────────
	a.statusBar = tview.NewTextView().SetDynamicColors(true)
	a.statusBar.SetBackgroundColor(tcell.ColorDefault)

	// ── Root layout ──────────────────────────────────────────────────────────
	a.mainFlex = tview.NewFlex().
		AddItem(sidebar, 30, 0, true).
		AddItem(diffPanel, 0, 1, false).
		AddItem(a.rightPanel, 0, 1, false)

	root := tview.NewFlex().SetDirection(tview.FlexRow).
		AddItem(a.header, 1, 0, false).
		AddItem(a.mainFlex, 0, 1, true).
		AddItem(a.helpBar, 1, 0, false).
		AddItem(a.statusBar, 1, 0, false)

	a.pages = tview.NewPages().AddPage("main", root, true, true)

	a.tv.SetInputCapture(func(event *tcell.EventKey) *tcell.EventKey {
		return a.handleInput(event)
	})
	a.tv.SetRoot(a.pages, true).EnableMouse(false)
}

func (a *application) refreshHeader() {
	a.header.SetText(fmt.Sprintf(
		" [::b]gitdiff[-:-:-]  [yellow]%s[-]  →  [cyan]%s[-]  (on [green]%s[-])  [[darkgray]theme: %s[-]]",
		tview.Escape(a.branchA), tview.Escape(a.bLabel()), tview.Escape(getCurrentBranch()), a.theme.name,
	))
}

func (a *application) refreshHelpBar() {
	t := a.theme
	var text string
	if a.editMode {
		text = fmt.Sprintf(
			" [%s]^S[-]: Save  [%s]^X[-]: Revert  [%s]^G[-]: File list  [%s]Esc[-]: Exit edit",
			t.helpBarText, t.helpBarText, t.helpBarText, t.helpBarText,
		)
	} else {
		delStatus := "on"
		if !a.showDeleted {
			delStatus = "off"
		}
		text = fmt.Sprintf(
			" [%s]j/k[-]: Move  [%s]e[-]: Edit  [%s]^D/^U[-]: Scroll  [%s]^R[-]: Del(%s)  [%s]^P[-]: Panel  [%s]b[-]: Branch  [%s]t[-]: Theme  [%s]q[-]: Quit",
			t.helpBarText, t.helpBarText, t.helpBarText, t.helpBarText, delStatus,
			t.helpBarText, t.helpBarText, t.helpBarText, t.helpBarText,
		)
	}
	a.helpBar.SetText(text)
}

func (a *application) applyTheme() {
	t := a.theme
	a.header.SetBackgroundColor(t.headerBg)
	a.sidebarTitle.SetBackgroundColor(t.sidebarTitleBg)
	a.diffTitle.SetBackgroundColor(t.diffTitleBg)
	a.editorTitle.SetBackgroundColor(t.editorTitleBg)
	a.helpBar.SetBackgroundColor(t.helpBarBg)
	a.fileList.SetBackgroundColor(t.contentBg)
	a.diffView.SetBackgroundColor(t.contentBg)
	a.editorView.SetBackgroundColor(t.contentBg)
	a.refreshHeader()
	a.refreshHelpBar()
	// Reload current file to update diff colors
	if len(a.files) > 0 {
		a.refreshEditorView()
		diffText := getFileDiff(a.branchA, a.branchB, a.files[a.currentIdx].path)
		if diffText != "" {
			a.diffView.SetText(highlightDiff(diffText, t.chromaStyle)).ScrollToBeginning()
		}
	}
	a.tv.Draw()
}

func (a *application) toggleTheme() {
	if a.theme.name == "Dark" {
		a.theme = lightTheme
	} else {
		a.theme = darkTheme
	}
	a.applyTheme()
	a.notify(fmt.Sprintf("Theme: %s", a.theme.name), false)
}

func (a *application) populateFileList() {
	a.fileList.Clear()
	for _, f := range a.files {
		style, ok := statusStyles[f.status]
		if !ok {
			style = statusStyle{color: "white", badge: "[?]", desc: "Unknown"}
		}
		st := a.stats[f.path]
		label := fmt.Sprintf("[%s]%s[-]  %s", style.color, style.badge, tview.Escape(f.path))
		if st.added != "-" && st.added != "" {
			label += fmt.Sprintf("  [green]+%s[-] [red]-%s[-]", st.added, st.deleted)
		}
		a.fileList.AddItem(label, "", 0, nil)
	}
}

func (a *application) handleInput(event *tcell.EventKey) *tcell.EventKey {
	// Let modal pages handle their own input.
	if name, _ := a.pages.GetFrontPage(); name == "modal" {
		return event
	}

	if a.editMode {
		switch event.Key() {
		case tcell.KeyEscape:
			a.exitEditMode()
			return nil
		case tcell.KeyCtrlS:
			a.writeOut()
			return nil
		case tcell.KeyCtrlX:
			a.revertFile()
			return nil
		case tcell.KeyCtrlG:
			a.exitEditMode()
			a.tv.SetFocus(a.fileList)
			return nil
		}
		return event
	}

	// Normal mode
	switch event.Key() {
	case tcell.KeyRune:
		switch event.Rune() {
		case 'q':
			a.tv.Stop()
			return nil
		case 'j':
			a.moveDown()
			return nil
		case 'k':
			a.moveUp()
			return nil
		case 'e':
			a.enterEditMode()
			return nil
		case 'b':
			a.showChangeBranch()
			return nil
		case 't':
			a.toggleTheme()
			return nil
		}
	case tcell.KeyDown:
		a.moveDown()
		return nil
	case tcell.KeyUp:
		a.moveUp()
		return nil
	case tcell.KeyCtrlD:
		row, _ := a.diffView.GetScrollOffset()
		_, _, _, h := a.diffView.GetInnerRect()
		a.diffView.ScrollTo(row+h/2, 0)
		return nil
	case tcell.KeyCtrlU:
		row, _ := a.diffView.GetScrollOffset()
		_, _, _, h := a.diffView.GetInnerRect()
		if newRow := row - h/2; newRow > 0 {
			a.diffView.ScrollTo(newRow, 0)
		} else {
			a.diffView.ScrollTo(0, 0)
		}
		return nil
	case tcell.KeyCtrlR:
		a.toggleDeleted()
		return nil
	case tcell.KeyCtrlP:
		a.toggleEditorPanel()
		return nil
	case tcell.KeyCtrlG:
		a.tv.SetFocus(a.fileList)
		return nil
	}
	return event
}

func (a *application) moveDown() {
	cur := a.fileList.GetCurrentItem()
	if cur < a.fileList.GetItemCount()-1 {
		a.fileList.SetCurrentItem(cur + 1)
	}
}

func (a *application) moveUp() {
	cur := a.fileList.GetCurrentItem()
	if cur > 0 {
		a.fileList.SetCurrentItem(cur - 1)
	}
}

// loadFile fetches the diff once and updates both the center and right panels.
func (a *application) loadFile(idx int) {
	if idx < 0 || idx >= len(a.files) {
		return
	}
	fi := a.files[idx]
	diffText := getFileDiff(a.branchA, a.branchB, fi.path)

	// ── Center panel ─────────────────────────────────────────────────────────
	style, ok := statusStyles[fi.status]
	if !ok {
		style = statusStyle{badge: "[?]", desc: "Unknown"}
	}
	a.diffTitle.SetText(fmt.Sprintf(" %s %s  [%s]", style.badge, tview.Escape(fi.path), style.desc))
	if diffText != "" {
		a.diffView.SetText(highlightDiff(diffText, a.theme.chromaStyle)).ScrollToBeginning()
	} else {
		a.diffView.SetText("[::d]No textual diff (binary file or no changes)[-:-:-]")
	}

	// ── Right panel ──────────────────────────────────────────────────────────
	if fi.status == "D" || a.repoRoot == "" {
		a.diffLines = nil
		a.editorView.SetText("[::d](deleted file)[-:-:-]")
		a.editorTitle.SetText(" Editor  [::d](deleted)[-:-:-]")
		return
	}
	if diffText == "" {
		a.diffLines = nil
		a.editorView.SetText("[::d](no diff available)[-:-:-]")
		a.editorTitle.SetText(fmt.Sprintf(" Editor  [::d]%s[-:-:-]", tview.Escape(fi.path)))
		return
	}

	a.diffLines = parseDiffLines(diffText)
	a.refreshEditorView()
	a.updateEditorTitle(false)
}

func (a *application) refreshEditorView() {
	if len(a.diffLines) == 0 {
		a.editorView.SetText("[::d]No diff data available.[-:-:-]")
		return
	}
	a.editorView.SetText(buildEditorView(a.diffLines, a.showDeleted, a.theme)).ScrollToBeginning()
}

func (a *application) updateEditorTitle(editMode bool) {
	if len(a.files) == 0 {
		return
	}
	fi := a.files[a.currentIdx]
	if editMode {
		a.editorTitle.SetText(fmt.Sprintf(
			" [::b]%s[-:-:-]  [::d]^S Save  ^X Revert  ^G File List[-:-:-]",
			tview.Escape(fi.path),
		))
	} else {
		delTag := "[green]on[-]"
		if !a.showDeleted {
			delTag = "[red]off[-]"
		}
		a.editorTitle.SetText(fmt.Sprintf(
			" [::b]%s[-:-:-]  [::d]e Edit  ^R Del:%s  ^G List[-:-:-]",
			tview.Escape(fi.path), delTag,
		))
	}
}

func (a *application) enterEditMode() {
	if len(a.files) == 0 || a.repoRoot == "" {
		return
	}
	fi := a.files[a.currentIdx]
	if fi.status == "D" {
		a.notify("Cannot edit a deleted file.", true)
		return
	}
	content, err := os.ReadFile(filepath.Join(a.repoRoot, fi.path))
	if err != nil {
		content = []byte{}
	}
	a.editor.SetText(string(content), true)
	a.editMode = true
	// Keep the colored diff view on top; add editor below it for reference while editing.
	a.rightPanel.AddItem(a.editor, 0, 1, true)
	a.tv.SetFocus(a.editor)
	a.updateEditorTitle(true)
	a.refreshHelpBar()
}

func (a *application) exitEditMode() {
	if !a.editMode {
		return
	}
	a.editMode = false
	a.rightPanel.RemoveItem(a.editor)
	a.tv.SetFocus(a.fileList)
	a.updateEditorTitle(false)
	a.refreshHelpBar()
}

func (a *application) writeOut() {
	if len(a.files) == 0 || a.repoRoot == "" {
		return
	}
	fi := a.files[a.currentIdx]
	if fi.status == "D" {
		a.notify("Cannot save a deleted file.", true)
		return
	}
	fpath := filepath.Join(a.repoRoot, fi.path)
	if err := os.WriteFile(fpath, []byte(a.editor.GetText()), 0644); err != nil {
		a.notify(fmt.Sprintf("Error saving: %v", err), true)
		return
	}
	a.notify(fmt.Sprintf("Saved: %s", fi.path), false)

	// Refresh diff and editor view after save.
	diffText := getFileDiff(a.branchA, a.branchB, fi.path)
	a.diffLines = parseDiffLines(diffText)
	if diffText != "" {
		a.diffView.SetText(highlightDiff(diffText, a.theme.chromaStyle)).ScrollToBeginning()
	}
	a.refreshEditorView()
}

func (a *application) revertFile() {
	if len(a.files) == 0 || a.repoRoot == "" {
		return
	}
	fi := a.files[a.currentIdx]
	if fi.status == "D" {
		return
	}
	content, err := os.ReadFile(filepath.Join(a.repoRoot, fi.path))
	if err != nil {
		content = []byte{}
	}
	a.editor.SetText(string(content), true)
	a.notify(fmt.Sprintf("Reverted: %s", fi.path), false)
}

func (a *application) toggleDeleted() {
	a.showDeleted = !a.showDeleted
	label := "shown"
	if !a.showDeleted {
		label = "hidden"
	}
	a.notify(fmt.Sprintf("Deleted lines: %s", label), false)
	a.refreshEditorView()
	a.updateEditorTitle(a.editMode)
	a.refreshHelpBar()
}

func (a *application) toggleEditorPanel() {
	a.showEditor = !a.showEditor
	if a.showEditor {
		a.mainFlex.AddItem(a.rightPanel, 0, 1, false)
	} else {
		if a.editMode {
			a.exitEditMode()
		}
		a.mainFlex.RemoveItem(a.rightPanel)
		a.tv.SetFocus(a.fileList)
	}
}

func (a *application) showChangeBranch() {
	form := tview.NewForm()
	form.SetBorder(true).
		SetTitle(" Change Comparison Branches ").
		SetTitleAlign(tview.AlignCenter).
		SetBackgroundColor(a.theme.modalBg)
	form.AddInputField("Branch A:", a.branchA, 30, nil, nil)
	form.AddInputField("Branch B:", a.branchB, 30, nil, nil)

	dismiss := func() {
		a.pages.RemovePage("modal")
		a.tv.SetFocus(a.fileList)
	}
	applyFn := func() {
		newA := strings.TrimSpace(form.GetFormItem(0).(*tview.InputField).GetText())
		newB := strings.TrimSpace(form.GetFormItem(1).(*tview.InputField).GetText())
		dismiss()
		if newA == "" {
			return
		}
		if !checkRef(newA) {
			a.notify(fmt.Sprintf("'%s' is not a valid branch or ref.", newA), true)
			return
		}
		if newB != "" && !checkRef(newB) {
			a.notify(fmt.Sprintf("'%s' is not a valid branch or ref.", newB), true)
			return
		}
		files, err := getDiffFiles(newA, newB)
		if err != nil {
			a.notify(fmt.Sprintf("Error: %v", err), true)
			return
		}
		a.branchA = newA
		a.branchB = newB
		a.files = files
		a.stats = getFileStats(newA, newB)
		a.currentIdx = 0
		a.reloadFileList()
		a.refreshHeader()
	}

	form.AddButton("Cancel", dismiss)
	form.AddButton("Apply", applyFn)
	form.SetCancelFunc(dismiss)

	// Center the form as an overlay.
	modal := tview.NewFlex().
		AddItem(nil, 0, 1, false).
		AddItem(tview.NewFlex().SetDirection(tview.FlexRow).
			AddItem(nil, 0, 1, false).
			AddItem(form, 13, 0, true).
			AddItem(nil, 0, 1, false),
			62, 0, true).
		AddItem(nil, 0, 1, false)

	a.pages.AddPage("modal", modal, true, true)
	a.tv.SetFocus(form)
}

func (a *application) reloadFileList() {
	a.sidebarTitle.SetText(fmt.Sprintf(" Files (%d)", len(a.files)))
	a.populateFileList()

	if len(a.files) > 0 {
		a.fileList.SetCurrentItem(0)
		a.loadFile(0)
	} else {
		a.diffTitle.SetText(fmt.Sprintf(" %s  →  %s", a.branchA, a.bLabel()))
		a.diffView.SetText("[::d]No differences between the selected branches.[-:-:-]")
		a.editorView.SetText("")
		a.editorTitle.SetText(" Editor")
	}
}

func (a *application) notify(msg string, isError bool) {
	if isError {
		a.statusBar.SetText(fmt.Sprintf(" [::b][red]✗ %s[-:-:-]", tview.Escape(msg)))
	} else {
		a.statusBar.SetText(fmt.Sprintf(" [green]✓ %s[-:-:-]", tview.Escape(msg)))
	}
	a.tv.Draw()
}

func (a *application) run() error {
	if len(a.files) > 0 {
		a.loadFile(0)
	}
	a.tv.SetFocus(a.fileList)
	return a.tv.Run()
}

// ─── Entry point ──────────────────────────────────────────────────────────────

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "Usage: gitdiff <branch-a> [<branch-b>]")
		fmt.Fprintf(os.Stderr, "\nKeys:\n")
		fmt.Fprintf(os.Stderr, "  j/k      move file list     Ctrl+D/U  scroll diff\n")
		fmt.Fprintf(os.Stderr, "  e        enter edit mode    Ctrl+G    back to file list\n")
		fmt.Fprintf(os.Stderr, "  Ctrl+S   save file          Ctrl+X    revert file\n")
		fmt.Fprintf(os.Stderr, "  Ctrl+R   toggle deleted     Ctrl+P    toggle editor panel\n")
		fmt.Fprintf(os.Stderr, "  b        change branches    t         toggle theme\n")
		fmt.Fprintf(os.Stderr, "  q        quit\n")
		os.Exit(1)
	}

	branchA := os.Args[1]
	branchB := ""
	if len(os.Args) >= 3 {
		branchB = os.Args[2]
	}

	if !checkGitRepo() {
		fmt.Fprintln(os.Stderr, "Error: not inside a git repository.")
		os.Exit(1)
	}
	if !checkRef(branchA) {
		fmt.Fprintf(os.Stderr, "Error: '%s' is not a valid branch or ref.\n", branchA)
		os.Exit(1)
	}
	if branchB != "" && !checkRef(branchB) {
		fmt.Fprintf(os.Stderr, "Error: '%s' is not a valid branch or ref.\n", branchB)
		os.Exit(1)
	}

	files, err := getDiffFiles(branchA, branchB)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
	if len(files) == 0 {
		bLabel := branchB
		if bLabel == "" {
			bLabel = "working tree"
		}
		fmt.Printf("No differences between '%s' and '%s'.\n", branchA, bLabel)
		os.Exit(0)
	}

	stats := getFileStats(branchA, branchB)
	if err := newApplication(branchA, branchB, files, stats).run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
