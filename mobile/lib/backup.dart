import 'dart:async';
import 'dart:io';
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:photo_manager/photo_manager.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';

const _chunkSize = 8 * 1024 * 1024;
const _doneKey = 'backed_up_asset_ids';

class BackupProgress {
  BackupProgress({
    this.total = 0,
    this.done = 0,
    this.skipped = 0,
    this.uploaded = 0,
    this.failed = 0,
    this.current = '',
    this.currentFraction = 0,
    this.running = false,
    this.message = '',
  });
  int total;
  int done; // finished one way or another (uploaded, already there, failed)
  int skipped; // already on the server
  int uploaded;
  int failed;
  String current;
  double currentFraction;
  bool running;
  String message;
}

class _Prepared {
  _Prepared(this.asset, this.file, this.filename, this.hash);
  final AssetEntity asset;
  final File file;
  final String filename;
  final String hash;
}

/// Backs up the camera roll: hash each item, ask the server which hashes it already has,
/// upload the rest in resumable chunks. Items that finished are remembered on the phone so
/// the next run only looks at new photos.
class BackupService {
  BackupService(this.api, this.onProgress);

  final GharBoxApi api;
  final void Function(BackupProgress) onProgress;
  final progress = BackupProgress();
  bool _cancel = false;

  void cancel() => _cancel = true;

  Future<bool> requestPermission() async {
    final ps = await PhotoManager.requestPermissionExtend();
    return ps.hasAccess;
  }

  Future<List<AssetEntity>> _allAssets() async {
    final paths = await PhotoManager.getAssetPathList(type: RequestType.common, onlyAll: true);
    if (paths.isEmpty) return [];
    final all = paths.first;
    final count = await all.assetCountAsync;
    final out = <AssetEntity>[];
    for (var page = 0; page * 500 < count; page++) {
      out.addAll(await all.getAssetListPaged(page: page, size: 500));
    }
    return out;
  }

  Future<void> run() async {
    if (progress.running) return;
    _cancel = false;
    progress
      ..running = true
      ..message = 'Looking for new photos and videos…'
      ..done = 0
      ..skipped = 0
      ..uploaded = 0
      ..failed = 0;
    onProgress(progress);

    final prefs = await SharedPreferences.getInstance();
    final doneIds = (prefs.getStringList(_doneKey) ?? []).toSet();
    Future<void> markDone(String id) async {
      doneIds.add(id);
      await prefs.setStringList(_doneKey, doneIds.toList());
    }

    try {
      final assets = (await _allAssets()).where((a) => !doneIds.contains(a.id)).toList();
      progress.total = assets.length;
      if (assets.isEmpty) {
        progress.message = 'Everything is backed up.';
        return;
      }
      for (var i = 0; i < assets.length && !_cancel; i += 40) {
        final batch = assets.sublist(i, min(i + 40, assets.length));
        final prepared = <_Prepared>[];
        for (final asset in batch) {
          if (_cancel) break;
          try {
            prepared.addAll(await _prepare(asset));
          } catch (_) {
            progress.failed++;
            progress.done++;
            onProgress(progress);
          }
        }
        final existing = prepared.isEmpty
            ? <String>{}
            : await api.existingHashes(prepared.map((p) => p.hash).toList());
        final finishedAssets = <String, bool>{};
        for (final p in prepared) {
          if (_cancel) break;
          var ok = true;
          if (existing.contains(p.hash)) {
            progress.skipped++;
          } else {
            ok = await _upload(p);
          }
          finishedAssets[p.asset.id] = (finishedAssets[p.asset.id] ?? true) && ok;
        }
        for (final entry in finishedAssets.entries) {
          if (entry.value) await markDone(entry.key);
          progress.done++;
          if (!entry.value) progress.failed++;
        }
        progress.message = 'Backing up ${progress.done} of ${progress.total}';
        onProgress(progress);
      }
      if (progress.uploaded > 0 || progress.failed > 0) {
        try {
          await api.reportBackup(
              uploaded: progress.uploaded,
              skipped: progress.skipped,
              failed: progress.failed,
              device: Platform.isIOS ? 'iPhone' : 'Android phone');
        } catch (_) {/* the backup itself worked; the notification is optional */}
      }
      progress.message = _cancel
          ? 'Paused. ${progress.total - progress.done} items left.'
          : progress.failed > 0
              ? 'Done, but ${progress.failed} items failed. Run again to retry them.'
              : 'Everything is backed up.';
    } on ApiException catch (e) {
      progress.message = e.status == 401 ? 'Signed out. Sign in again to continue.' : e.message;
    } on SocketException {
      progress.message = "Can't reach your GharBox server. Are you on your home Wi-Fi?";
    } catch (e) {
      progress.message = 'Backup stopped: $e';
    } finally {
      progress
        ..running = false
        ..current = ''
        ..currentFraction = 0;
      onProgress(progress);
      unawaited(PhotoManager.clearFileCache());
    }
  }

  /// One asset can produce two files: a Live Photo has the still image and a short video.
  Future<List<_Prepared>> _prepare(AssetEntity asset) async {
    progress.current = await asset.titleAsync;
    progress.message = 'Checking ${progress.current}';
    onProgress(progress);
    final out = <_Prepared>[];
    final file = await asset.originFile; // downloads from iCloud if needed
    if (file == null) throw Exception('Could not read ${progress.current}');
    out.add(_Prepared(asset, file, _nameFor(asset, file, await asset.titleAsync), await _hash(file)));
    if (asset.isLivePhoto) {
      try {
        final motion = await asset.loadFile(isOrigin: true, withSubtype: true);
        if (motion != null && motion.path != file.path) {
          final base = (await asset.titleAsync).replaceAll(RegExp(r'\.[^.]+$'), '');
          out.add(_Prepared(asset, motion, _nameFor(asset, motion, '$base.MOV'), await _hash(motion)));
        }
      } catch (_) {/* the still image is still backed up */}
    }
    return out;
  }

  String _nameFor(AssetEntity asset, File file, String title) {
    if (title.isNotEmpty) return title;
    final ext = file.path.contains('.') ? file.path.split('.').last : 'jpg';
    return '${asset.id.replaceAll(RegExp(r'[^A-Za-z0-9]'), '_')}.$ext';
  }

  Future<String> _hash(File file) async => (await sha256.bind(file.openRead()).first).toString();

  Future<bool> _upload(_Prepared p) async {
    final size = await p.file.length();
    final year = p.asset.createDateTime.year;
    progress
      ..current = p.filename
      ..currentFraction = 0
      ..message = 'Uploading ${p.filename}';
    onProgress(progress);
    var state = await api.createUpload(
      filename: p.filename,
      size: size,
      folder: '/Camera Roll/$year',
      sha256: p.hash,
      takenAt: p.asset.createDateTime,
      deviceAssetId: p.asset.id,
    );
    if (state.status != 'uploading') {
      progress.uploaded++;
      return true;
    }
    final raf = await p.file.open();
    try {
      var retries = 0;
      while (state.status == 'uploading' && !_cancel) {
        try {
          await raf.setPosition(state.offset);
          final bytes = await raf.read(_chunkSize);
          state = await api.uploadChunk(state.id!, state.offset, bytes);
          retries = 0;
        } on ApiException catch (e) {
          if (e.status != 409 && e.status < 500) rethrow; // 409 = offset mismatch: resync below
          if (++retries > 5) rethrow;
          await Future.delayed(Duration(seconds: 2 * retries));
          state = await api.uploadStatus(state.id!);
        } on SocketException {
          if (++retries > 5) rethrow;
          await Future.delayed(Duration(seconds: 2 * retries));
          state = await api.uploadStatus(state.id!);
        } on TimeoutException {
          if (++retries > 5) rethrow;
          state = await api.uploadStatus(state.id!);
        }
        progress.currentFraction = size == 0 ? 1 : state.offset / size;
        onProgress(progress);
      }
      if (state.status == 'uploading') return false; // cancelled; resumes next run from scratch
      progress.uploaded++;
      return true;
    } on ApiException {
      return false;
    } finally {
      await raf.close();
    }
  }
}
