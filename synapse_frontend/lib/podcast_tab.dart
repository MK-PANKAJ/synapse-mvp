import 'package:flutter/material.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

class PodcastTab extends StatefulWidget {
  final String content; 
  final Function onGenerate; 
  final bool isLoading;
  final bool isGenerating;  // NEW: For async background generation

  PodcastTab({
    required this.content, 
    required this.onGenerate, 
    required this.isLoading,
    this.isGenerating = false,
  });

  @override
  _PodcastTabState createState() => _PodcastTabState();
}

class _PodcastTabState extends State<PodcastTab> {
  final FlutterTts flutterTts = FlutterTts();
  bool isPlaying = false;

  @override
  void dispose() {
    flutterTts.stop();
    super.dispose();
  }

  Future<void> _speak() async {
    if (widget.content.isEmpty) return;
    
    if (isPlaying) {
      await flutterTts.stop();
      setState(() => isPlaying = false);
    } else {
      setState(() => isPlaying = true);
      await flutterTts.setLanguage("hi-IN"); // Base locale for Hinglish
      
      // Split content into dialogue lines
      List<String> lines = widget.content.split('\n');
      
      for (String line in lines) {
        if (!mounted || !isPlaying) break;
        if (line.trim().isEmpty) continue;

        // VOICE MODULATION LOGIC
        if (line.contains("**Max**") || line.contains("Max:")) {
            // Student: Energetic, higher pitch, FAST (ADHD friendly)
            await flutterTts.setPitch(1.1);
            await flutterTts.setSpeechRate(0.9); // Was 0.6
        } else if (line.contains("**Dr. V**") || line.contains("Dr. V:")) {
             // Professor: Calm, lower pitch, normal speed
            await flutterTts.setPitch(0.9); 
            await flutterTts.setSpeechRate(0.7); // Was 0.4
        } else {
            // Narrator / Default
            await flutterTts.setPitch(1.0);
            await flutterTts.setSpeechRate(0.8); // Was 0.5
        }
        
        // Speak the clean text 
        // FILTER: Remove stage directions in (), [], or **
        String textToSpeak = line.replaceAll(RegExp(r'\(.*?\)|\[.*?\]|\*.*?\*'), "").trim();
        
        if (textToSpeak.isNotEmpty) {
             await flutterTts.awaitSpeakCompletion(true);
             await flutterTts.speak(textToSpeak);
        }
      }
      
      if (mounted) setState(() => isPlaying = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    // Show generating state if podcast is being created in background
    if (widget.isGenerating) {
        return Center(
            child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                    CircularProgressIndicator(),
                    SizedBox(height: 16),
                    Text("Crafting your podcast... 🎙️", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                    SizedBox(height: 8),
                    Text("This usually takes 30-60 seconds", style: TextStyle(color: Colors.grey, fontSize: 14)),
                ],
            ),
        );
    }
    
    if (widget.isLoading) {
      return Center(child: CircularProgressIndicator());
    }

    if (widget.content.isEmpty) {
      return Center(
        child: ElevatedButton.icon(
          icon: Icon(Icons.podcasts),
          label: Text("Generate AI Podcast (Hinglish)"),
          onPressed: () => widget.onGenerate(),
        ),
      );
    }
    
    return Column(
      children: [
        Container(
          padding: EdgeInsets.all(16),
          color: Colors.deepPurple.shade50,
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text("Synapse FM - Ep. 1", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 18)),
              IconButton(
                icon: Icon(isPlaying ? Icons.stop_circle : Icons.play_circle_fill, size: 50, color: Colors.deepPurple),
                onPressed: _speak,
              )
            ],
          ),
        ),
        Expanded(
          child: SingleChildScrollView(
            padding: EdgeInsets.all(16),
            child: MarkdownBody(data: widget.content),
          ),
        ),
      ],
    );
  }
}
