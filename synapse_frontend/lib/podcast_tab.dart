import 'package:flutter/material.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

class PodcastTab extends StatefulWidget {
  final String content; 
  final Function onGenerate; 
  final bool isLoading;

  PodcastTab({required this.content, required this.onGenerate, required this.isLoading});

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
      // Use Hindi (India) locale for proper Hinglish pronunciation
      await flutterTts.setLanguage("hi-IN"); 
      await flutterTts.setPitch(1.0);
      await flutterTts.speak(widget.content);
      
      flutterTts.setCompletionHandler(() {
        if (mounted) setState(() => isPlaying = false);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
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
