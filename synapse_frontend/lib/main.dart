import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';
import 'dart:html' as html;
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:markdown/markdown.dart' as md;
import 'package:flutter_math_fork/flutter_math.dart';
import 'package:file_picker/file_picker.dart';
import 'package:url_launcher/url_launcher.dart';
import 'podcast_tab.dart';

void main() {
  runApp(SynapseApp());
}

class SynapseApp extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Synapse',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        primarySwatch: Colors.indigo,
        useMaterial3: true,
        textTheme: GoogleFonts.lexendDecaTextTheme(), // Accessible Font
      ),
      home: DashboardScreen(),
    );
  }
}

class DashboardScreen extends StatefulWidget {
  @override
  _DashboardScreenState createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  final TextEditingController _urlController = TextEditingController();
  
  // Data States
  String _currentSummary = "";
  List<dynamic> _focusPoints = [];
  String _currentPodcastScript = "";
  String _currentVideoId = "";
  String _transcriptContext = "";
  String _mermaidCode = "";
  String _selectedProfile = "ADHD"; // Default
  final List<String> _profiles = ["ADHD", "Dyslexia", "Visual", "Hinglish"];
  
  bool _isLoading = false;
  bool _isPodcastLoading = false;
  
  final String userID = "student_01"; 
  // NOTE: Replace with 10.0.2.2 for Emulator or Cloud Run URL for Production
  final String backendUrl = "https://synapse-backend-232524391998.us-central1.run.app"; 

  Future<void> _processVideo() async {
    if (_urlController.text.isEmpty) return;
    
    setState(() => _isLoading = true);
    try {
      final response = await http.post(
        Uri.parse('$backendUrl/api/v1/ingest'),
        headers: {"Content-Type": "application/json"},
        body: jsonEncode({
          "user_id": userID,
          "video_url": _urlController.text,
          "user_profile": _selectedProfile
        }),
      ).timeout(Duration(seconds: 90)); // Timeout at 1.5 mins (User feedback: 5m is too long)
      
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        
        // Defensive: safely get summary_data OR content (backend uses 'content')
        String rawSummaryJson = (data['summary_data'] ?? data['content'] ?? "").toString();
        
        // Clean markdown
        rawSummaryJson = rawSummaryJson.replaceAll("```json", "").replaceAll("```", "").trim();
        
        // Decode inner JSON
        Map<String, dynamic> aiContent = {};
        try {
            if (rawSummaryJson.startsWith("{")) {
                aiContent = jsonDecode(rawSummaryJson);
            } else {
                aiContent = {"summary": rawSummaryJson};
            }
        } catch (e) {
            print("Inner JSON Parse Error: $e");
            
            // REGEX FALLBACK: Manually extract fields if JSON is slightly broken
            String summaryVal = "";
            try {
                // Extract summary: "summary": "(...)"
                final sumMatch = RegExp(r'"summary":\s*"(.*?)(?<!\\)"', dotAll: true).firstMatch(rawSummaryJson);
                if (sumMatch != null) summaryVal = sumMatch.group(1) ?? "";
            } catch (_) {}
            
            if (summaryVal.isNotEmpty) {
                 // Unescape basic JSON characters for readable text
                 // FIX: Also unescape \$ to $ for LaTeX rendering
                 summaryVal = summaryVal.replaceAll(r'\\n', '\n').replaceAll(r'\"', '"').replaceAll(r'\\$', r'$');
                 aiContent['summary'] = summaryVal;
            } else {
                 aiContent['summary'] = rawSummaryJson; // Ultimate fallback
            }
            
            // Extract Focus Points
             try {
                final focusMatch = RegExp(r'"focus_points":\s*\[(.*?)\]', dotAll: true).firstMatch(rawSummaryJson);
                if (focusMatch != null) {
                    final rawList = focusMatch.group(1)!;
                    // Split by comma+quote to roughly get items
                    final items = rawList.split(RegExp(r'",\s*"'));
                    aiContent['focus_points'] = items.map((s) => s.replaceAll('"', '').trim()).toList();
                }
            } catch (_) {}

            // Extract Mermaid
            try {
                 final merMatch = RegExp(r'"mermaid_diagram":\s*"(.*?)(?<!\\)"', dotAll: true).firstMatch(rawSummaryJson);
                 if (merMatch != null) {
                     String rawMermaid = merMatch.group(1)?.replaceAll(r'\\n', '\n').replaceAll(r'\"', '"') ?? "";
                     // SANITIZER: Remove HTML tags (like <sub>, <br>) as they break mermaid.ink
                     _mermaidCode = rawMermaid.replaceAll(RegExp(r'<[^>]*>', multiLine: true, caseSensitive: false), "");
                     aiContent['mermaid_diagram'] = _mermaidCode;
                 }
            } catch (_) {}
        }

        setState(() {
          _currentSummary = aiContent['summary']?.toString() ?? "No summary available.";
          
          // Safe List Conversion
          var rawFocus = aiContent['focus_points'];
          if (rawFocus is List) {
             _focusPoints = rawFocus.map((e) => e.toString()).toList();
          } else {
             _focusPoints = [];
          }

          _mermaidCode = aiContent['mermaid_diagram']?.toString() ?? "";
          _currentVideoId = data['lecture_id']?.toString() ?? "";
          _transcriptContext = data['transcript_context']?.toString() ?? "";
          _currentPodcastScript = ""; 
        });
      } else {
        setState(() => _currentSummary = "Server Error (${response.statusCode}): ${response.body}");
      }
    } catch (e) {
      // If error is empty or timeout, show explicit message
      String errorMsg = e.toString();
      if (errorMsg.contains("Timeout")) {
          errorMsg = "Request timed out. The video might be too long or the server is busy.";
      }
      setState(() => _currentSummary = "Connection/Processing Error: $errorMsg");
    }
    setState(() => _isLoading = false);
  }

  Future<void> _pickAndUploadVideo() async {
      FilePickerResult? result = await FilePicker.platform.pickFiles(type: FileType.video);
      
      if (result != null) {
          setState(() => _isLoading = true);
          PlatformFile file = result.files.first;
          
          // WEB vs MOBILE: usage differs, but for MVP web we use bytes
          // Note: For large files in prod, we'd use signed URLs. usage here is simple multipart.
          var request = http.MultipartRequest("POST", Uri.parse('$backendUrl/api/v1/upload'));
          
          if (file.bytes != null) {
              // WEB
              request.files.add(http.MultipartFile.fromBytes('file', file.bytes!, filename: file.name));
          } else {
             // MOBILE (not active, but safe fallback)
             print("File path missing (common on web without bytes)");
             setState(() { _isLoading = false; _currentSummary = "Error: File selection failed."; });
             return;
          }

          try {
              var streamedResponse = await request.send();
              var response = await http.Response.fromStream(streamedResponse);
              
              if (response.statusCode == 200) {
                  var data = jsonDecode(response.body);
                  String videoUri = data['video_uri'];
                  
                  // Now Ingest
                  _urlController.text = videoUri; // Show URI to user
                  await _processVideo(); // Reuse ingest logic
              } else {
                   setState(() => _currentSummary = "Upload Failed: ${response.body}");
              }
          } catch (e) {
              setState(() => _currentSummary = "Upload Error: $e");
          }
           setState(() => _isLoading = false);
      }
  }

  Future<void> _generatePodcast() async {
    if (_transcriptContext.isEmpty) return;
    
    setState(() => _isPodcastLoading = true);
    try {
        final response = await http.post(
            Uri.parse('$backendUrl/api/v1/generate-podcast'),
            headers: {"Content-Type": "application/json"},
            body: jsonEncode({"transcript_text": _transcriptContext})
        );
        
        if (response.statusCode == 200) {
            final data = jsonDecode(response.body);
            setState(() => _currentPodcastScript = data['script']);
        }
    } catch (e) {
        print(e);
    }
    setState(() => _isPodcastLoading = false);
  }

  void _openDoubtModal() {
    if (_currentVideoId.isEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("Please ingest a video first!")));
        return;
    }
    showModalBottomSheet(
      context: context, 
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) => DoubtSheet(
          backendUrl: backendUrl, 
          userId: userID, 
          lectureId: _currentVideoId,
          userProfile: _selectedProfile // Pass profile
      )
    );
  }



  void _launchMermaidEditor() async {
      if (_mermaidCode.isEmpty) return;
      
      final jsonState = jsonEncode({
        "code": _mermaidCode,
        "mermaid": {"theme": "default"}
      });
      final base64State = base64Encode(utf8.encode(jsonState));
      final url = Uri.parse("https://mermaid.live/edit#pako:$base64State"); 
      // Simple fallback if pako fails:
      final simpleUrl = Uri.parse("https://mermaid.live/edit#$base64State");
      
      try {
        if (!await launchUrl(simpleUrl)) {
            ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("Could not launch Mermaid Editor")));
        }
      } catch (e) {
         print("Launch Error: $e");
         // Fallback for some web blockers
         html.window.open(simpleUrl.toString(), 'new tab');
      }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text("Synapse Dashboard"),
        actions: [
            DropdownButton<String>(
                value: _selectedProfile,
                dropdownColor: Colors.white,
                underline: Container(),
                icon: Icon(Icons.psychology, color: Colors.indigo),
                onChanged: (val) => setState(() => _selectedProfile = val!),
                items: _profiles.map((p) => DropdownMenuItem(value: p, child: Text(p))).toList()
            ),
            SizedBox(width: 16)
        ],
      ),
      body: Padding(
        padding: EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 1. INPUT
            TextField(
              controller: _urlController,
              decoration: InputDecoration(
                labelText: "Paste Lecture Link",
                border: OutlineInputBorder(),
                suffixIcon: IconButton(
                  icon: Icon(Icons.auto_awesome, color: Colors.indigo),
                  onPressed: _processVideo,
                ),
              ),
            ),
            SizedBox(height: 10),
            
            // OR UPLOAD BUTTON
            Row(children: [
                Expanded(child: Divider()),
                Padding(padding: EdgeInsets.symmetric(horizontal: 10), child: Text("OR")),
                Expanded(child: Divider()),
            ]),
            SizedBox(height: 10),
            
            SizedBox(
                width: double.infinity,
                child: OutlinedButton.icon(
                    onPressed: _isLoading ? null : _pickAndUploadVideo,
                    icon: Icon(Icons.upload_file),
                    label: Text("Upload Video File (MP4)"),
                    style: OutlinedButton.styleFrom(padding: EdgeInsets.all(16))
                )
            ),
            SizedBox(height: 20),
            
            // 2. TABS (Summary vs Bingo vs Podcast)
            if (_isLoading) Expanded(child: Center(child: CircularProgressIndicator())),
            
            if (!_isLoading && _currentSummary.isNotEmpty)
                Expanded(
                    child: DefaultTabController(
                        length: 4,
                        child: Column(
                            children: [
                                TabBar(
                                    labelColor: Colors.indigo,
                                    tabs: [
                                        Tab(icon: Icon(Icons.article), text: "Summary"),
                                        Tab(icon: Icon(Icons.bolt), text: "Focus"),
                                        Tab(icon: Icon(Icons.hub), text: "Visual"),
                                        Tab(icon: Icon(Icons.headphones), text: "Podcast"),
                                    ]
                                ),
                                Expanded(
                                    child: TabBarView(
                                        children: [
                                            // SUMMARY TAB
                                            Container(
                                                padding: EdgeInsets.all(16),
                                                margin: EdgeInsets.symmetric(vertical: 8),
                                                decoration: BoxDecoration(color: Colors.indigo.shade50, borderRadius: BorderRadius.circular(8)),
                                                child: SingleChildScrollView(
                                                    child: MarkdownBody(
                                                        data: _currentSummary,
                                                        builders: {
                                                            'latex': LatexElementBuilder(),
                                                        },
                                                        extensionSet: md.ExtensionSet(
                                                            md.ExtensionSet.gitHubFlavored.blockSyntaxes,
                                                            [md.EmojiSyntax(), ...md.ExtensionSet.gitHubFlavored.inlineSyntaxes, LatexSyntax()]
                                                        ),
                                                    )
                                                )
                                            ),
                                            
                                            // FOCUS TAB (FORMERLY BINGO)
                                            _focusPoints.isEmpty 
                                            ? Center(child: Text("No focus points found."))
                                            : ListView.builder(
                                                padding: EdgeInsets.all(16),
                                                itemCount: _focusPoints.length,
                                                itemBuilder: (ctx, i) {
                                                    return Card(
                                                        elevation: 2,
                                                        margin: EdgeInsets.only(bottom: 12),
                                                        color: Colors.amber.shade50,
                                                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                                                        child: Padding(
                                                            padding: EdgeInsets.all(16),
                                                            child: Text(
                                                                _focusPoints[i], 
                                                                style: TextStyle(fontSize: 16, fontWeight: FontWeight.w500, color: Colors.indigo.shade900)
                                                            ),
                                                        ),
                                                    );
                                                }
                                            ),

                                            // VISUAL TAB
                                            _mermaidCode.isEmpty
                                            ? Center(child: Text("No visual diagram available for this content."))
                                            : Container(
                                                padding: EdgeInsets.all(16),
                                                color: Colors.white,
                                                child: Column(children: [
                                                    // 1. RENDERED DIAGRAM (via mermaid.ink)
                                                    Expanded(
                                                        child: Center(
                                                            child: Image.network(
                                                                "https://mermaid.ink/img/${base64Encode(utf8.encode(_mermaidCode))}",
                                                                loadingBuilder: (ctx, child, loadingProgress) {
                                                                    if (loadingProgress == null) return child;
                                                                    return CircularProgressIndicator();
                                                                },
                                                                errorBuilder: (ctx, error, stackTrace) => 
                                                                    SingleChildScrollView(child: SelectableText(_mermaidCode)), // Fallback to code
                                                            )
                                                        )
                                                    ),
                                                    SizedBox(height: 10),
                                                    
                                                    // 2. ACTION BUTTONS
                                                    Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                                                        ElevatedButton.icon(
                                                            icon: Icon(Icons.edit),
                                                            label: Text("Edit in Live Editor"),
                                                            onPressed: _launchMermaidEditor,
                                                        ),
                                                        SizedBox(width: 10),
                                                        TextButton(
                                                            child: Text("View Source Code"),
                                                            onPressed: () {
                                                                showDialog(context: context, builder: (ctx) => AlertDialog(
                                                                    content: SingleChildScrollView(
                                                                        child: MarkdownBody(
                                                                            data: _mermaidCode,
                                                                            builders: {
                                                                                'latex': LatexElementBuilder(),
                                                                            },
                                                                            extensionSet: md.ExtensionSet(
                                                                                md.ExtensionSet.gitHubFlavored.blockSyntaxes,
                                                                                [md.EmojiSyntax(), ...md.ExtensionSet.gitHubFlavored.inlineSyntaxes, LatexSyntax()]
                                                                            ),
                                                                        )
                                                                    )
                                                                ));
                                                            } 
                                                        )
                                                    ])
                                                ])
                                            ),
                                            
                                            // PODCAST TAB


                                            PodcastTab(
                                                content: _currentPodcastScript,
                                                onGenerate: _generatePodcast,
                                                isLoading: _isPodcastLoading,
                                            )
                                        ]
                                    )
                                )
                            ],
                        )
                    ),
                )
            else if (!_isLoading)
                Expanded(child: Center(child: Text("Paste a URL to start.")))
          ],
        ),
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _openDoubtModal,
        label: Text("Ask Doubt"),
        icon: Icon(Icons.help),
        backgroundColor: Colors.indigo,
      ),
    );
  }
}

class DoubtSheet extends StatefulWidget {
  final String backendUrl;
  final String userId;
  final String lectureId;
  final String userProfile; // New Field

  DoubtSheet({
      required this.backendUrl, 
      required this.userId, 
      required this.lectureId,
      required this.userProfile
  });

  @override
  _DoubtSheetState createState() => _DoubtSheetState();
}

class _DoubtSheetState extends State<DoubtSheet> {
  final TextEditingController _qController = TextEditingController();
  String _answer = "Ask me anything about the lecture!";
  bool _asking = false;

  Future<void> _ask() async {
    if (_qController.text.isEmpty) return;
    
    setState(() { 
        _answer = "Thinking...";
        _asking = true;
    });

    try {
        final response = await http.post(
          Uri.parse('${widget.backendUrl}/api/v1/ask-doubt'),
          headers: {"Content-Type": "application/json"},
          body: jsonEncode({
            "user_id": widget.userId,
            "lecture_id": widget.lectureId, 
            "question": _qController.text,
            "user_profile": widget.userProfile // Send to backend
          }),
        );
        
        if (response.statusCode == 200) {
            final data = jsonDecode(response.body);
            setState(() => _answer = data['answer']);
        } else {
            setState(() => _answer = "Error: ${response.statusCode}");
        }
    } catch (e) {
        setState(() => _answer = "Error: $e");
    }
    
    setState(() => _asking = false);
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 600,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.vertical(top: Radius.circular(20))
      ),
      padding: EdgeInsets.fromLTRB(24, 24, 24, MediaQuery.of(context).viewInsets.bottom + 24),
      child: Column(
        children: [
          Text("Doubt Resolver", style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
          SizedBox(height: 20),
          Expanded(
            child: Container(
              width: double.infinity,
              padding: EdgeInsets.all(12),
              decoration: BoxDecoration(
                  color: Colors.grey[100],
                  borderRadius: BorderRadius.circular(12)
              ),
              child: SingleChildScrollView(child: Text(_answer, style: TextStyle(fontSize: 16))),
            ),
          ),
          SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: TextField(
                    controller: _qController, 
                    decoration: InputDecoration(hintText: "Why is this...", border: OutlineInputBorder()),
                    onSubmitted: (_) => _ask(),
                )
              ),
              SizedBox(width: 8),
              if (_asking) 
                CircularProgressIndicator() 
              else 
                IconButton(icon: Icon(Icons.send, color: Colors.indigo), onPressed: _ask)
            ],
          )
        ],
      ),
    );
  }

}

// --- CUSTOM SYNTAX FOR LATEX ($...$) ---

class LatexSyntax extends md.InlineSyntax {
  LatexSyntax() : super(r'(\$\$[\s\S]*?\$\$)|(\$[^$]*?\$)');

  @override
  bool onMatch(md.InlineParser parser, Match match) {
    String raw = match.group(0)!;
    bool isBlock = raw.startsWith(r'$$');
    String content = isBlock ? raw.substring(2, raw.length - 2) : raw.substring(1, raw.length - 1);
    
    md.Element el = md.Element.text('latex', content);
    el.attributes['style'] = isBlock ? 'block' : 'inline';
    parser.addNode(el);
    return true;
  }
}

class LatexElementBuilder extends MarkdownElementBuilder {
  @override
  Widget? visitElement(md.Element element, TextStyle? preferredStyle) {
    final String content = element.textContent;
    final bool isBlock = element.attributes['style'] == 'block';

    return Math.tex(
        content,
        textStyle: preferredStyle?.copyWith(fontFamily: 'SansSerif'),
        mathStyle: isBlock ? MathStyle.display : MathStyle.text,
    );
  }
}
