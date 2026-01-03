import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';
import 'package:flutter_markdown/flutter_markdown.dart';

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
  List<dynamic> _bingoTerms = [];
  String _currentPodcastScript = "";
  String _currentVideoId = "";
  String _transcriptContext = "";
  
  bool _isLoading = false;
  bool _isPodcastLoading = false;
  
  final String userID = "student_01"; 
  // NOTE: Replace with 10.0.2.2 for Emulator or Cloud Run URL for Production
  final String backendUrl = "http://127.0.0.1:8080"; 

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
          "user_profile": "ADHD" 
        }),
      );
      
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        
        // Parse the AI content which is usually a JSON string in our prompt structure
        // But if it's raw text (fallback), we handle that too.
        String contentRaw = data['content'];
        String summary = contentRaw;
        List<dynamic> bingo = [];
        
        try {
            // Try to clean markdown fences if present
            String cleanJson = contentRaw.replaceAll("```json", "").replaceAll("```", "").trim();
            final parsedContent = jsonDecode(cleanJson);
            summary = parsedContent['summary'];
            bingo = parsedContent['bingo_terms'] ?? [];
        } catch (e) {
            print("JSON Parse Error (keeping raw text): $e");
        }

        setState(() {
          _currentSummary = summary;
          _bingoTerms = bingo;
          _currentVideoId = data['lecture_id'];
          _transcriptContext = data['transcript_context'];
          _currentPodcastScript = ""; // Reset podcast on new video
        });
      } else {
        setState(() => _currentSummary = "Error: ${response.body}");
      }
    } catch (e) {
      setState(() => _currentSummary = "Connection Error: $e");
    }
    setState(() => _isLoading = false);
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
      builder: (ctx) => DoubtSheet(backendUrl: backendUrl, userId: userID, lectureId: _currentVideoId)
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text("Synapse Dashboard")),
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
            
            // 2. TABS (Summary vs Bingo vs Podcast)
            if (_isLoading) Expanded(child: Center(child: CircularProgressIndicator())),
            
            if (!_isLoading && _currentSummary.isNotEmpty)
                Expanded(
                    child: DefaultTabController(
                        length: 3,
                        child: Column(
                            children: [
                                TabBar(
                                    labelColor: Colors.indigo,
                                    tabs: [
                                        Tab(icon: Icon(Icons.article), text: "Summary"),
                                        Tab(icon: Icon(Icons.grid_on), text: "Bingo"),
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
                                                child: SingleChildScrollView(child: MarkdownBody(data: _currentSummary))
                                            ),
                                            
                                            // BINGO TAB
                                            _bingoTerms.isEmpty 
                                            ? Center(child: Text("No Bingo terms found."))
                                            : GridView.builder(
                                                padding: EdgeInsets.all(16),
                                                gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                                                    crossAxisCount: 3,
                                                    crossAxisSpacing: 10, 
                                                    mainAxisSpacing: 10
                                                ),
                                                itemCount: _bingoTerms.length,
                                                itemBuilder: (ctx, i) {
                                                    return InkWell(
                                                        onTap: () {}, // Handle tap to "collect"
                                                        child: Container(
                                                            decoration: BoxDecoration(
                                                                color: Colors.amber.shade100,
                                                                borderRadius: BorderRadius.circular(12),
                                                                border: Border.all(color: Colors.amber)
                                                            ),
                                                            child: Center(child: Text(_bingoTerms[i], textAlign: TextAlign.center, style: TextStyle(fontWeight: FontWeight.bold))),
                                                        ),
                                                    );
                                                }
                                            ),
                                            
                                            // PODCAST TAB
                                            Column(
                                                children: [
                                                    SizedBox(height: 10),
                                                    ElevatedButton.icon(
                                                        onPressed: _isPodcastLoading ? null : _generatePodcast, 
                                                        icon: Icon(Icons.auto_awesome), 
                                                        label: Text("Generate AI Podcast Script")
                                                    ),
                                                    Expanded(
                                                        child: _isPodcastLoading 
                                                        ? Center(child: CircularProgressIndicator()) 
                                                        : Container(
                                                            width: double.infinity,
                                                            margin: EdgeInsets.only(top: 10),
                                                            padding: EdgeInsets.all(16),
                                                            decoration: BoxDecoration(color: Colors.grey.shade100, borderRadius: BorderRadius.circular(8)),
                                                            child: SingleChildScrollView(child: Text(_currentPodcastScript.isEmpty ? "Tap button to generate!" : _currentPodcastScript))
                                                        )
                                                    )
                                                ],
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
  DoubtSheet({required this.backendUrl, required this.userId, required this.lectureId});

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
            "question": _qController.text
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
