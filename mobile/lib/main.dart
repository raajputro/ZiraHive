import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:photo_manager/photo_manager.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:wakelock_plus/wakelock_plus.dart';

import 'api.dart';
import 'backup.dart';

// Bengal indigo and jute, same palette as the web app.
const indigoNight = Color(0xFF1F2A44);
const indigo = Color(0xFF2E4A8B);
const jute = Color(0xFFC9A66B);

void main() => runApp(const GharBoxApp());

class GharBoxApp extends StatelessWidget {
  const GharBoxApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'GharBox',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: indigo, primary: indigo, secondary: jute),
        useMaterial3: true,
      ),
      home: const StartScreen(),
    );
  }
}

const _secure = FlutterSecureStorage();

/// Decides between sign-in and the backup screen based on what's saved.
class StartScreen extends StatefulWidget {
  const StartScreen({super.key});
  @override
  State<StartScreen> createState() => _StartScreenState();
}

class _StartScreenState extends State<StartScreen> {
  GharBoxApi? _api;
  String? _username;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _restore();
  }

  Future<void> _restore() async {
    final prefs = await SharedPreferences.getInstance();
    final server = prefs.getString('server');
    final token = await _secure.read(key: 'token');
    if (server != null && token != null) {
      _api = GharBoxApi(server, token: token);
      _username = prefs.getString('username');
    }
    setState(() => _loading = false);
  }

  Future<void> _signedIn(GharBoxApi api, String username) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('server', api.baseUrl);
    await prefs.setString('username', username);
    await _secure.write(key: 'token', value: api.token);
    setState(() {
      _api = api;
      _username = username;
    });
  }

  Future<void> _signOut() async {
    await _secure.delete(key: 'token');
    setState(() => _api = null);
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Scaffold(backgroundColor: indigoNight);
    if (_api == null) return SignInScreen(onSignedIn: _signedIn);
    return BackupScreen(api: _api!, username: _username ?? '', onSignOut: _signOut);
  }
}

class SignInScreen extends StatefulWidget {
  const SignInScreen({super.key, required this.onSignedIn});
  final Future<void> Function(GharBoxApi, String) onSignedIn;
  @override
  State<SignInScreen> createState() => _SignInScreenState();
}

class _SignInScreenState extends State<SignInScreen> {
  final _server = TextEditingController(text: 'http://192.168.0.100:8080');
  final _user = TextEditingController();
  final _pass = TextEditingController();
  String _error = '';
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    SharedPreferences.getInstance().then((p) {
      final saved = p.getString('server');
      if (saved != null) _server.text = saved;
    });
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = '';
    });
    try {
      var url = _server.text.trim();
      if (!url.startsWith('http')) url = 'http://$url';
      final api = GharBoxApi(url);
      await api.health();
      final username = await api.login(_user.text.trim(), _pass.text);
      await widget.onSignedIn(api, username);
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } catch (_) {
      setState(() => _error = "Can't reach that address. Check the server address and that your phone is on the same Wi-Fi.");
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: indigoNight,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Card(
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
              child: Padding(
                padding: const EdgeInsets.fromLTRB(24, 28, 24, 24),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const Text('ঘর', style: TextStyle(fontSize: 44, color: Color(0xFF8A6A33), height: 1)),
                    const SizedBox(height: 12),
                    Text('Sign in to GharBox', style: Theme.of(context).textTheme.headlineSmall),
                    const SizedBox(height: 4),
                    const Text('Your PC address and port, for example http://192.168.0.105:8080'),
                    const SizedBox(height: 20),
                    TextField(controller: _server, keyboardType: TextInputType.url, autocorrect: false,
                        decoration: const InputDecoration(labelText: 'Server address')),
                    TextField(controller: _user, autocorrect: false,
                        decoration: const InputDecoration(labelText: 'Username')),
                    TextField(controller: _pass, obscureText: true,
                        decoration: const InputDecoration(labelText: 'Password'),
                        onSubmitted: (_) => _submit()),
                    if (_error.isNotEmpty) ...[
                      const SizedBox(height: 12),
                      Text(_error, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                    ],
                    const SizedBox(height: 20),
                    FilledButton(
                      onPressed: _busy ? null : _submit,
                      child: Padding(
                        padding: const EdgeInsets.symmetric(vertical: 12),
                        child: Text(_busy ? 'Signing in…' : 'Sign in'),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class BackupScreen extends StatefulWidget {
  const BackupScreen({super.key, required this.api, required this.username, required this.onSignOut});
  final GharBoxApi api;
  final String username;
  final VoidCallback onSignOut;
  @override
  State<BackupScreen> createState() => _BackupScreenState();
}

class _BackupScreenState extends State<BackupScreen> with WidgetsBindingObserver {
  late final BackupService _service;
  BackupProgress _p = BackupProgress(message: 'Ready to back up your camera roll.');
  bool _permission = true;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _service = BackupService(widget.api, (p) {
      if (mounted) setState(() => _p = p);
      if (!p.running) WakelockPlus.disable();
    });
    _start(); // back up new photos every time the app opens
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _service.cancel();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed && !_p.running) _start();
  }

  Future<void> _start() async {
    final ok = await _service.requestPermission();
    setState(() => _permission = ok);
    if (!ok) return;
    // Phones pause apps in the background, so keep the screen on while backing up.
    await WakelockPlus.enable();
    await _service.run();
  }

  @override
  Widget build(BuildContext context) {
    final p = _p;
    final overall = p.total == 0 ? (p.running ? null : 1.0) : p.done / p.total;
    final text = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(
        backgroundColor: indigoNight,
        foregroundColor: Colors.white,
        title: const Text('GharBox'),
        actions: [
          IconButton(
            tooltip: 'Sign out',
            icon: const Icon(Icons.logout),
            onPressed: p.running ? null : widget.onSignOut,
          ),
        ],
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Camera roll backup', style: text.headlineSmall),
              Text('Signed in as ${widget.username} on ${widget.api.baseUrl}', style: text.bodySmall),
              const SizedBox(height: 28),
              if (!_permission) ...[
                const Text('GharBox needs access to your photos to back them up. '
                    'Allow full access in Settings, then come back.'),
                const SizedBox(height: 12),
                OutlinedButton(onPressed: PhotoManagerOpenSettings.open, child: const Text('Open Settings')),
              ] else ...[
                ClipRRect(
                  borderRadius: BorderRadius.circular(6),
                  child: LinearProgressIndicator(value: overall, minHeight: 10, color: jute,
                      backgroundColor: const Color(0xFFE3E6EC)),
                ),
                const SizedBox(height: 12),
                Text(p.message, style: text.titleMedium),
                if (p.running && p.current.isNotEmpty) ...[
                  const SizedBox(height: 4),
                  Text('${p.current}  ${(p.currentFraction * 100).round()}%', style: text.bodySmall),
                ],
                const SizedBox(height: 24),
                Wrap(spacing: 24, runSpacing: 12, children: [
                  _Stat('Uploaded', p.uploaded),
                  _Stat('Already backed up', p.skipped),
                  _Stat('Failed', p.failed),
                ]),
                const Spacer(),
                SizedBox(
                  width: double.infinity,
                  child: p.running
                      ? OutlinedButton(onPressed: _service.cancel, child: const Text('Pause backup'))
                      : FilledButton(onPressed: _start, child: const Text('Back up now')),
                ),
                const SizedBox(height: 8),
                Text('Keep the app open while it backs up. Backup continues where it left off.',
                    style: text.bodySmall),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _Stat extends StatelessWidget {
  const _Stat(this.label, this.value);
  final String label;
  final int value;
  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('$value', style: Theme.of(context).textTheme.headlineMedium),
          Text(label, style: Theme.of(context).textTheme.bodySmall),
        ],
      );
}

/// photo_manager exposes the settings shortcut on PhotoManager itself.
class PhotoManagerOpenSettings {
  static void open() => PhotoManager.openSetting();
}
