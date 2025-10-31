import dgram from 'dgram';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { spawn } from 'child_process';
import ffmpegStatic from 'ffmpeg-static';

export function registerVideoRoutes(app, houstonConfigPath, readJSON) {
  // Video stream acquisition endpoints (separated module)
  // Controls whether Houston acquires/releases a UDP port by spawning ffmpeg or binding a local UDP socket.
  // activeStreams[key] may contain: { socket, ffmpeg, proc, clients, acc, startedAt }
  const activeStreams = {}; // key = `${group}:${sysid}` -> entry

  function streamKey(groupId, sysid) {
    return `${groupId}:${sysid}`;
  }

  // Allocate ports as pairs (RTP, RTCP). Many RTP stacks (ffmpeg) will bind
  // to the specified port and also attempt to bind the next port for RTCP.
  // To avoid cross-stream conflicts (RTCP of stream N colliding with RTP of
  // stream N+1), allocate ports with a stride of 2 per sysid.
  function portForSid(base, sid) {
    const n = parseInt(sid, 10) || 1;
    return base + (n - 1) * 2;
  }

  app.get('/api/streams', (req, res) => {
    const cfg = readJSON(houstonConfigPath, { groups: [] });
    const globalVideo = cfg.video || {};
    const entries = [];
    (cfg.groups || []).forEach((g) => {
      const sysids = g.sysids || [];
      sysids.forEach((s) => {
        const sid = String(s);
        const key = streamKey(g.id, sid);
  const host = (g.video_streams && g.video_streams[sid] && g.video_streams[sid].host) || globalVideo.host || '127.0.0.1';
  const base = globalVideo.base_port || 5600;
  const port = (g.video_streams && g.video_streams[sid] && g.video_streams[sid].port) || portForSid(base, sid);
        const codec = (g.video_streams && g.video_streams[sid] && g.video_streams[sid].codec) || globalVideo.codec || 'h264';
  const pid = activeStreams[key]?.proc?.pid || activeStreams[key]?.ffmpeg?.pid || null;
  entries.push({ group: g.id, sysid: sid, effectiveHost: host, effectivePort: port, effectiveCodec: codec, active: !!activeStreams[key], pid });
      });
    });
    res.json({ streams: entries });
  });

  app.post('/api/streams/:group/:sysid/start', (req, res) => {
    const { group, sysid } = req.params;
    const cfg = readJSON(houstonConfigPath, { groups: [] });
    const groupCfg = (cfg.groups || []).find(g => g.id === group);
    if (!groupCfg) return res.status(404).json({ error: 'group not found' });
    const globalVideo = cfg.video || {};
  const sid = String(sysid);
  const host = (groupCfg.video_streams && groupCfg.video_streams[sid] && groupCfg.video_streams[sid].host) || globalVideo.host || '127.0.0.1';
  const base = globalVideo.base_port || 5600;
  const port = (groupCfg.video_streams && groupCfg.video_streams[sid] && groupCfg.video_streams[sid].port) || portForSid(base, sid);
  const key = streamKey(group, sid);
    // Determine behavior: spawn_on_start means ffmpeg will own the UDP port and perform decoding.
    const spawnOnStart = !!globalVideo.spawn_on_start;
  const codec = (groupCfg.video_streams && groupCfg.video_streams[sid] && groupCfg.video_streams[sid].codec) || globalVideo.codec || 'h264';

    // If an entry exists and it's already an ffmpeg instance, report already active.
    if (activeStreams[key] && activeStreams[key].ffmpeg) return res.status(400).json({ error: 'stream already active' });

    // Ensure we have an entry object
    if (!activeStreams[key]) activeStreams[key] = { clients: [], acc: Buffer.alloc(0), ffmpeg: null, socket: null, startedAt: Date.now() };

    if (spawnOnStart) {
      // If a previous socket was bound for this stream, close it before spawning ffmpeg.
      if (activeStreams[key].socket) {
        try {
          activeStreams[key].socket.close();
          console.log(`[Houston] closed previous udp socket for ${key} before spawning ffmpeg`);
        } catch (e) {
          console.warn(`[Houston] error closing socket for ${key}:`, e && e.message);
        }
        // clear socket reference so ffmpeg can bind the port
        activeStreams[key].socket = null;
      }

  // Spawn ffmpeg to read from the UDP input and produce MJPEG on stdout.
      try {
        if (activeStreams[key].ffmpeg) return res.status(400).json({ error: 'ffmpeg already running' });
        if (!ffmpegStatic) {
          console.error('ffmpeg-static not available');
          return res.status(500).json({ error: 'ffmpeg not available' });
        }
        let args;
        let tmpSdpPath = null;
        let input;
        if (codec === 'h264') {
          // create an SDP file for RTP H264 input so ffmpeg can depacketize correctly
          // Respect optional config flags to control RTCP/RTCP-mux behavior so we don't
          // accidentally bind RTCP ports that collide with adjacent streams.
          const disableRtcp = !!globalVideo.disable_rtcp;
          const rtcpMux = !!globalVideo.rtcp_mux;
          // base SDP lines
          let sdp = `v=0\no=- 0 0 IN IP4 ${host}\ns=stream\nc=IN IP4 ${host}\nt=0 0\nm=video ${port} RTP/AVP 96\na=rtpmap:96 H264/90000\n`;
          // if RTCP multiplexing is enabled, inform ffmpeg (RTCP on same port)
          if (rtcpMux) {
            sdp += 'a=rtcp-mux\n';
          }
          // if RTCP is disabled, set rtcp port to 0 (many demuxers interpret as no separate RTCP)
          if (disableRtcp) {
            sdp += 'a=rtcp:0\n';
          }
          tmpSdpPath = path.join(os.tmpdir(), `wayfarer-${group}-${sid}-${Date.now()}.sdp`);
          fs.writeFileSync(tmpSdpPath, sdp, 'utf8');
          input = tmpSdpPath;
          args = ['-protocol_whitelist', 'file,udp,rtp', '-hide_banner', '-loglevel', 'error', '-i', tmpSdpPath, '-f', 'mjpeg', '-q:v', '5', '-r', '15', '-'];
        } else {
          input = `udp://${host}:${port}`;
          args = ['-hide_banner', '-loglevel', 'error', '-i', input, '-f', 'mjpeg', '-q:v', '5', '-r', '15', '-'];
        }
        console.log(`[Houston] spawning ffmpeg on Start for ${key} -> ${input}`);
        const proc = spawn(ffmpegStatic, args, { stdio: ['ignore', 'pipe', 'pipe'] });
        activeStreams[key].ffmpeg = proc;
        activeStreams[key].acc = Buffer.alloc(0);

        proc.on('exit', (code, sig) => {
          console.log(`[Houston] ffmpeg exited for ${key} code=${code} sig=${sig}`);
          // notify clients and cleanup
          (activeStreams[key]?.clients || []).forEach((r) => { try { r.end(); } catch (e) {} });
          // remove tmp sdp if created
          try { if (tmpSdpPath && fs.existsSync(tmpSdpPath)) fs.unlinkSync(tmpSdpPath); } catch(e){}
          delete activeStreams[key];
        });

        // log ffmpeg stderr for diagnostics
  proc.stderr && proc.stderr.on('data', (d) => { console.log(`[Houston][ffmpeg:${key}] ${d.toString()}`); });

        proc.stdout.on('data', (chunk) => {
          console.log(`[Houston][ffmpeg-output:${key}] stdout ${chunk.length} bytes`);
          const entry = activeStreams[key];
          if (!entry) return;
          entry.acc = Buffer.concat([entry.acc, chunk]);
          let start = entry.acc.indexOf(Buffer.from([0xff, 0xd8]));
          let end = entry.acc.indexOf(Buffer.from([0xff, 0xd9]), start >= 0 ? start + 2 : 0);
          while (start >= 0 && end > start) {
            const frame = entry.acc.slice(start, end + 2);
            entry.acc = entry.acc.slice(end + 2);
            const header = `--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ${frame.length}\r\n\r\n`;
            const payload = Buffer.concat([Buffer.from(header, 'utf8'), frame, Buffer.from('\r\n')]);
            // write payload to each client; log and remove any clients that error
            (entry.clients || []).forEach((r) => {
              try {
                r.write(payload);
              } catch (e) {
                try { console.warn(`[Houston][mjpeg:${key}] write error to client: ${e && e.message}`); } catch (__) {}
                // remove failed client
                entry.clients = entry.clients.filter(x => x !== r);
                try { r.end(); } catch(__) {}
              }
            });
            start = entry.acc.indexOf(Buffer.from([0xff, 0xd8]));
            end = entry.acc.indexOf(Buffer.from([0xff, 0xd9]), start >= 0 ? start + 2 : 0);
          }
        });

        res.json({ ok: true, pid: proc.pid });
      } catch (e) {
        console.error('Failed to spawn ffmpeg on Start', e);
        res.status(500).json({ error: 'failed to spawn ffmpeg' });
      }
    } else {
      // Legacy behavior: bind and drop packets
      try {
        const socket = dgram.createSocket('udp4');
        socket.on('error', (err) => {
          console.log(`[Houston] udp socket error for ${key}:`, err.message || err);
        });
        socket.on('message', () => {});
        socket.bind({ address: host, port: port, exclusive: true }, () => {
          activeStreams[key] = { socket, startedAt: Date.now() };
          console.log(`[Houston] bound udp ${host}:${port} for ${key}`);
          res.json({ ok: true });
        });
      } catch (e) {
        console.error('Failed to bind UDP socket', e);
        res.status(500).json({ error: 'failed to bind UDP socket' });
      }
    }
  });

  app.post('/api/streams/:group/:sysid/stop', (req, res) => {
    const { group, sysid } = req.params;
    const key = streamKey(group, String(sysid));
    const entry = activeStreams[key];
    if (!entry) return res.status(404).json({ error: 'stream not active' });
    try {
      if (entry.ffmpeg) {
        // kill ffmpeg spawned by Start or Preview
        const pid = entry.ffmpeg.pid;
        try { entry.ffmpeg.kill('SIGTERM'); } catch (e) {}
        const timeout = setTimeout(() => { try { if (entry.ffmpeg && !entry.ffmpeg.killed) { entry.ffmpeg.kill('SIGKILL'); console.log(`[Houston] forcibly killed ffmpeg pid=${pid} for ${key}`); } } catch(e){} }, 3000);
        entry.ffmpeg.once('exit', ()=>{ clearTimeout(timeout); delete activeStreams[key]; });
      } else if (entry.proc) {
        entry.proc.kill('SIGTERM');
        const pid = entry.proc.pid;
        const timeout = setTimeout(() => { try { if (entry.proc && !entry.proc.killed) { entry.proc.kill('SIGKILL'); console.log(`[Houston] forcibly killed process pid=${pid} for ${key}`); } } catch(e){} }, 3000);
        entry.proc.once('exit', ()=>{ clearTimeout(timeout); delete activeStreams[key]; });
      } else if (entry.socket) {
        try {
          entry.socket.close(() => {
            delete activeStreams[key];
            console.log(`[Houston] closed udp socket for ${key}`);
          });
        } catch (e) {
          console.error('Error closing socket', e);
          delete activeStreams[key];
        }
      }
      res.json({ ok: true });
    } catch (e) {
      res.status(500).json({ error: 'failed to stop process' });
    }
  });

  // MJPEG streaming endpoint (low-latency viewer)
  app.get('/api/streams/:group/:sysid/mjpeg', (req, res) => {
    const { group, sysid } = req.params;
    const cfg = readJSON(houstonConfigPath, { groups: [] });
    const groupCfg = (cfg.groups || []).find(g => g.id === group);
    if (!groupCfg) return res.status(404).send('group not found');
    const globalVideo = cfg.video || {};
  const sid = String(sysid);
  const host = (groupCfg.video_streams && groupCfg.video_streams[sid] && groupCfg.video_streams[sid].host) || globalVideo.host || '127.0.0.1';
  const base = globalVideo.base_port || 5600;
  const port = (groupCfg.video_streams && groupCfg.video_streams[sid] && groupCfg.video_streams[sid].port) || portForSid(base, sid);
    const codec = (groupCfg.video_streams && groupCfg.video_streams[sid] && groupCfg.video_streams[sid].codec) || globalVideo.codec || 'h264';

    const key = streamKey(group, sid);
    if (!activeStreams[key]) activeStreams[key] = { clients: [], acc: Buffer.alloc(0), ffmpeg: null, socket: null, startedAt: Date.now() };
    const entry = activeStreams[key];

    // Response headers for multipart MJPEG
    res.writeHead(200, {
      'Cache-Control': 'no-cache, no-store, must-revalidate',
      'Pragma': 'no-cache',
      'Expires': '0',
      'Content-Type': 'multipart/x-mixed-replace; boundary=frame'
    });

    // Add client (log address) and track disconnects
    try {
      const clientAddr = (req.socket && (req.socket.remoteAddress + ':' + req.socket.remotePort)) || 'unknown';
      console.log(`[Houston][mjpeg:${key}] client connected ${clientAddr}`);
    } catch (e) {}
    entry.clients.push(res);

    // On client close, remove and possibly stop ffmpeg
    req.on('close', () => {
      try {
        const clientAddr = (req.socket && (req.socket.remoteAddress + ':' + req.socket.remotePort)) || 'unknown';
        console.log(`[Houston][mjpeg:${key}] client disconnected ${clientAddr}`);
      } catch (e) {}
      entry.clients = entry.clients.filter(r => r !== res);
      // if no clients and ffmpeg wasn't started by Start (i.e., spawn_on_start may be false), stop ffmpeg
      if ((entry.clients || []).length === 0 && !globalVideo.spawn_on_start) {
        if (entry.ffmpeg) {
          try { entry.ffmpeg.kill('SIGTERM'); } catch (e) {}
        }
      }
    });

    // Start ffmpeg if not running
    if (!entry.ffmpeg) {
      if (!ffmpegStatic) {
        console.error('ffmpeg-static not available');
        res.end();
        return;
      }
      let args;
      let tmpSdpPath = null;
      if (codec === 'h264') {
        const sdp = `v=0\no=- 0 0 IN IP4 ${host}\ns=stream\nc=IN IP4 ${host}\nt=0 0\nm=video ${port} RTP/AVP 96\na=rtpmap:96 H264/90000\n`;
        tmpSdpPath = path.join(os.tmpdir(), `wayfarer-mjpeg-${group}-${sid}-${Date.now()}.sdp`);
        fs.writeFileSync(tmpSdpPath, sdp, 'utf8');
        args = ['-protocol_whitelist', 'file,udp,rtp', '-hide_banner', '-loglevel', 'error', '-i', tmpSdpPath, '-f', 'mjpeg', '-q:v', '5', '-r', '15', '-'];
      } else {
        const input = `udp://${host}:${port}`;
        args = ['-hide_banner', '-loglevel', 'error', '-i', input, '-f', 'mjpeg', '-q:v', '5', '-r', '15', '-'];
      }

      console.log(`[Houston] spawning ffmpeg for MJPEG preview ${key}`);
      const proc = spawn(ffmpegStatic, args, { stdio: ['ignore', 'pipe', 'pipe'] });
      entry.ffmpeg = proc;
      entry.acc = Buffer.alloc(0);

      proc.stderr && proc.stderr.on('data', (d) => { console.log(`[Houston][ffmpeg:${key}] ${d.toString()}`); });

      proc.on('exit', (code, sig) => {
        console.log(`[Houston] ffmpeg exited for ${key} code=${code} sig=${sig}`);
        try { if (tmpSdpPath && fs.existsSync(tmpSdpPath)) fs.unlinkSync(tmpSdpPath); } catch(e){}
        (entry.clients || []).forEach((r) => { try { r.end(); } catch (e) {} });
        entry.clients = [];
        entry.ffmpeg = null;
      });

      proc.stdout.on('data', (chunk) => {
        console.log(`[Houston][ffmpeg-output:${key}] stdout ${chunk.length} bytes`);
        entry.acc = Buffer.concat([entry.acc, chunk]);
        let start = entry.acc.indexOf(Buffer.from([0xff, 0xd8]));
        let end = entry.acc.indexOf(Buffer.from([0xff, 0xd9]), start >= 0 ? start + 2 : 0);
        while (start >= 0 && end > start) {
          const frame = entry.acc.slice(start, end + 2);
          entry.acc = entry.acc.slice(end + 2);
          const header = `--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ${frame.length}\r\n\r\n`;
          const payload = Buffer.concat([Buffer.from(header, 'utf8'), frame, Buffer.from('\r\n')]);
          // write payload to each client; log and remove any clients that error
          (entry.clients || []).forEach((r) => {
            try {
              r.write(payload);
            } catch (e) {
              try { console.warn(`[Houston][mjpeg:${key}] write error to client: ${e && e.message}`); } catch (__) {}
              entry.clients = entry.clients.filter(x => x !== r);
              try { r.end(); } catch(__) {}
            }
          });
          start = entry.acc.indexOf(Buffer.from([0xff, 0xd8]));
          end = entry.acc.indexOf(Buffer.from([0xff, 0xd9]), start >= 0 ? start + 2 : 0);
        }
      });
    }
    // keep the response open
  });
}

export default registerVideoRoutes;
