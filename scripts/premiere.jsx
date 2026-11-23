// Runs inside Adobe Premiere Pro. premiere.py starts Premiere with a launcher that sets JOB and loads this file.
// It builds one project for one topic: the clips end to end on V1, the voices end to end on a free audio track,
// the longer of the two cut at its end, every clip scaled until it fills the frame, the logo on V2, then the export.
// This is ExtendScript (ES3): there is no JSON, Array.indexOf or String.trim.

var TICKS_PER_SECOND = 254016000000;    // Premiere's time unit

function samePath(a, b) {
    return String(a).replace(/\//g, "\\").toLowerCase() === String(b).replace(/\//g, "\\").toLowerCase();
}

function timeAt(ticks) {
    var time = new Time();
    time.ticks = String(ticks);
    return time;
}

function endTicks(track) {
    var count = track.clips.numItems;
    return count ? Number(track.clips[count - 1].end.ticks) : 0;
}

function seconds(ticks) {
    return Math.round(ticks / TICKS_PER_SECOND * 1000) / 1000;
}

function writeResult(fields) {
    var target = new File(JOB.result);
    var temporary = new File(JOB.result + ".tmp");      // renamed when complete, so premiere.py never reads half of it
    temporary.encoding = "UTF-8";
    temporary.open("w");
    for (var key in fields) {
        if (fields.hasOwnProperty(key)) temporary.writeln(key + "=" + String(fields[key]).replace(/[\r\n]+/g, " "));
    }
    temporary.close();
    temporary.rename(decodeURI(target.name));
}

function importInto(binName, paths) {
    var bin = app.project.rootItem.createBin(binName);
    if (!app.project.importFiles(paths, true, bin, false)) throw new Error("Premiere could not import the " + binName);
    var items = [];
    for (var i = 0; i < paths.length; i++) {
        var item = null;
        for (var j = 0; j < bin.children.numItems; j++) {
            if (samePath(bin.children[j].getMediaPath(), paths[i])) item = bin.children[j];
        }
        if (!item) throw new Error("not imported: " + paths[i]);
        items.push(item);
    }
    return items;
}

function placeEndToEnd(track, items, from) {
    for (var i = from; i < items.length; i++) {
        var start = endTicks(track);
        track.overwriteClip(items[i], String(start));
        var placed = track.clips[track.clips.numItems - 1];
        if (track.clips.numItems !== i + 1 || Number(placed.start.ticks) !== start) {
            throw new Error(items[i].name + " did not land at the end of the track");
        }
    }
}

function cutTrack(track, cut) {         // nothing of the track is left after `cut`
    for (var i = track.clips.numItems - 1; i >= 0; i--) {
        var clip = track.clips[i];
        if (Number(clip.start.ticks) >= cut) clip.remove(false, false);
        else if (Number(clip.end.ticks) > cut) clip.end = timeAt(cut);
    }
    if (endTicks(track) > cut) throw new Error("a track could not be cut at " + seconds(cut) + " s");
}

function motionProperty(motion, name, index) {
    for (var i = 0; i < motion.properties.numItems; i++) {
        if (motion.properties[i].displayName === name) return motion.properties[i];
    }
    return motion.properties[index];
}

function setMotion(clip, scale, position) {     // scale in percent; position [x, y] as parts of the frame, or nothing
    for (var i = 0; i < clip.components.numItems; i++) {
        var motion = clip.components[i];
        if (motion.matchName !== "AE.ADBE Motion") continue;
        var size = motionProperty(motion, "Scale", 1);
        size.setValue(scale, true);
        if (Math.abs(size.getValue() - scale) > 0.01) throw new Error("the scale of " + clip.name + " was not set");
        if (position) {
            var place = motionProperty(motion, "Position", 0);
            place.setValue(position, true);
            var now = place.getValue();
            if (Math.abs(now[0] - position[0]) > 0.001 || Math.abs(now[1] - position[1]) > 0.001) {
                throw new Error("the position of " + clip.name + " was not set (" + now + ")");
            }
        }
        return;
    }
    throw new Error(clip.name + " has no Motion effect");
}

function fillFrame(clip, width, height) {       // scale until the frame is full; what sticks out is cropped
    var scale = Math.max(JOB.width / width, JOB.height / height) * 100;
    setMotion(clip, scale);
    return scale;
}

function addLogo(sequence, cut) {               // on V2, over the whole video
    var logo = importInto("logo", [JOB.logo.path])[0];
    if (sequence.videoTracks.numTracks < 2) throw new Error("the sequence has no second video track for the logo");
    var track = sequence.videoTracks[1];
    track.overwriteClip(logo, "0");
    if (track.clips.numItems !== 1) throw new Error("the logo was not placed");
    var clip = track.clips[0];
    clip.end = timeAt(cut);
    if (Number(clip.start.ticks) !== 0 || Number(clip.end.ticks) !== cut) {
        throw new Error("the logo does not cover the whole video");
    }
    setMotion(clip, JOB.logo.scale, [JOB.logo.x, JOB.logo.y]);
}

function edit(result) {
    var i, paths = [];
    if (app.projects.numProjects) throw new Error("Premiere already has a project open");
    app.newProject(JOB.project);
    if (!samePath(app.project.path, JOB.project)) throw new Error("the project was not created (" + app.project.path + ")");

    for (i = 0; i < JOB.clips.length; i++) paths.push(JOB.clips[i].path);
    var clips = importInto("video_clips", paths);
    var voices = importInto("voices", JOB.voices);

    // The sequence takes the first clip's frame rate; only its frame size is changed.
    var sequence = app.project.createNewSequenceFromClips(JOB.sequence, [clips[0]], app.project.rootItem);
    if (!sequence) throw new Error("the sequence was not created");
    var settings = sequence.getSettings();
    settings.videoFrameWidth = JOB.width;
    settings.videoFrameHeight = JOB.height;
    sequence.setSettings(settings);
    if (Number(sequence.frameSizeHorizontal) !== JOB.width || Number(sequence.frameSizeVertical) !== JOB.height) {
        throw new Error("the sequence is " + sequence.frameSizeHorizontal + "x" + sequence.frameSizeVertical +
                        ", not " + JOB.width + "x" + JOB.height);
    }

    var video = sequence.videoTracks[0];
    placeEndToEnd(video, clips, 1);

    var narration = null;
    for (i = 0; i < sequence.audioTracks.numTracks; i++) {
        var track = sequence.audioTracks[i];
        if (track.clips.numItems) track.setMute(1);     // sound that came with a generated clip
        else if (!narration) narration = track;
    }
    if (!narration) throw new Error("the sequence has no free audio track for the voices");
    placeEndToEnd(narration, voices, 0);

    var frame = Number(sequence.timebase);              // ticks in one frame
    var videoEnd = endTicks(video), audioEnd = endTicks(narration);
    // The longer side is cut at its end: voices longer than the clips end with the last clip, and clips longer
    // than the voices end with the frame in which the voice ends.
    var cut = audioEnd < videoEnd ? Math.ceil(audioEnd / frame) * frame : videoEnd;
    for (i = 0; i < sequence.videoTracks.numTracks; i++) cutTrack(sequence.videoTracks[i], cut);
    for (i = 0; i < sequence.audioTracks.numTracks; i++) cutTrack(sequence.audioTracks[i], cut);

    result.scale = "";
    for (i = 0; i < video.clips.numItems; i++) {
        result.scale += (i ? "," : "") + fillFrame(video.clips[i], JOB.clips[i].width, JOB.clips[i].height);
    }
    if (JOB.logo) addLogo(sequence, cut);

    result.fps = TICKS_PER_SECOND / frame;
    result.videoSeconds = seconds(videoEnd);
    result.audioSeconds = seconds(audioEnd);
    result.cutSeconds = seconds(cut);
    result.clipsUsed = video.clips.numItems;

    app.project.save();
    var outcome = sequence.exportAsMediaDirect(JOB.output, JOB.preset, 0);    // 0 = the entire sequence
    result.exported = outcome;
    if (outcome !== "No Error") throw new Error("the export failed: " + outcome);
    app.project.save();
}

var result = { status: "OK" };
try {
    edit(result);
} catch (problem) {
    result.status = "ERROR";
    result.message = String(problem) + (problem.line ? " (premiere.jsx line " + problem.line + ")" : "");
}
writeResult(result);
// A project that failed is closed without saving, so Premiere does not stop to ask about it.
if (result.status !== "OK" && samePath(app.project.path, JOB.project)) app.project.closeDocument(0, 0);
app.quit();
