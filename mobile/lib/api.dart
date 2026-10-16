import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

class ApiException implements Exception {
  ApiException(this.status, this.message, [this.code]);
  final int status;
  final String message;
  final String? code; // e.g. "2fa_required"
  @override
  String toString() => message;
}

class UploadState {
  UploadState({this.id, required this.offset, required this.size, required this.status});
  final String? id;
  final int offset;
  final int size;
  final String status; // uploading | complete | exists

  factory UploadState.fromJson(Map<String, dynamic> j) => UploadState(
        id: j['id'] as String?,
        offset: (j['offset'] as num).toInt(),
        size: (j['size'] as num).toInt(),
        status: j['status'] as String,
      );
}

/// Talks to the GharBox server. Uses the same resumable upload protocol as the web app.
class GharBoxApi {
  GharBoxApi(String baseUrl, {this.token}) : baseUrl = baseUrl.replaceAll(RegExp(r'/+$'), '');

  final String baseUrl;
  String? token;
  final http.Client _client = http.Client();

  Map<String, String> get _headers => {
        if (token != null) 'Authorization': 'Bearer $token',
      };

  Uri _u(String path) => Uri.parse('$baseUrl$path');

  Future<dynamic> _send(http.BaseRequest req) async {
    req.headers.addAll(_headers);
    final res = await http.Response.fromStream(
        await _client.send(req).timeout(const Duration(minutes: 5)));
    if (res.statusCode >= 400) {
      var message = 'Server error ${res.statusCode}';
      String? code;
      try {
        final body = jsonDecode(res.body);
        final detail = body is Map ? body['detail'] : null;
        if (detail is String) message = detail;
        if (detail is Map) {
          message = (detail['message'] ?? message) as String;
          code = detail['code'] as String?;
        }
      } catch (_) {}
      throw ApiException(res.statusCode, message, code);
    }
    if (res.statusCode == 204 || res.body.isEmpty) return null;
    return jsonDecode(res.body);
  }

  Future<dynamic> _json(String method, String path, [Object? body]) {
    final req = http.Request(method, _u(path));
    if (body != null) {
      req.headers['Content-Type'] = 'application/json';
      req.body = jsonEncode(body);
    }
    return _send(req);
  }

  Future<void> health() async {
    final res = await _client.get(_u('/api/health')).timeout(const Duration(seconds: 8));
    if (res.statusCode != 200) throw ApiException(res.statusCode, 'This is not a GharBox server');
  }

  /// Returns the username on success and stores the token on this client.
  Future<String> login(String username, String password, {String? code}) async {
    final data = await _json('POST', '/api/auth/login', {
      'username': username,
      'password': password,
      if (code != null && code.isNotEmpty) 'code': code,
    });
    token = data['token'] as String;
    return data['user']['username'] as String;
  }

  Future<Set<String>> existingHashes(List<String> hashes) async {
    final data = await _json('POST', '/api/uploads/check', {'sha256': hashes});
    return (data['existing'] as List).cast<String>().toSet();
  }

  Future<UploadState> createUpload({
    required String filename,
    required int size,
    required String folder,
    required String sha256,
    DateTime? takenAt,
    String? deviceAssetId,
  }) async {
    final data = await _json('POST', '/api/uploads', {
      'filename': filename,
      'size': size,
      'folder': folder,
      'sha256': sha256,
      if (takenAt != null) 'taken_at': takenAt.toUtc().toIso8601String(),
      if (deviceAssetId != null) 'device_asset_id': deviceAssetId,
    });
    return UploadState.fromJson(data as Map<String, dynamic>);
  }

  Future<UploadState> uploadChunk(String id, int offset, Uint8List bytes) async {
    final req = http.Request('PATCH', _u('/api/uploads/$id'))
      ..headers['Upload-Offset'] = '$offset'
      ..headers['Content-Type'] = 'application/octet-stream'
      ..bodyBytes = bytes;
    return UploadState.fromJson(await _send(req) as Map<String, dynamic>);
  }

  /// Tells the server a backup run finished, so it shows up as a notification.
  Future<void> reportBackup({required int uploaded, required int skipped, required int failed, String? device}) =>
      _json('POST', '/api/events/backup', {
        'uploaded': uploaded,
        'skipped': skipped,
        'failed': failed,
        if (device != null) 'device': device,
      });

  Future<UploadState> uploadStatus(String id) async =>
      UploadState.fromJson(await _json('GET', '/api/uploads/$id') as Map<String, dynamic>);
}
