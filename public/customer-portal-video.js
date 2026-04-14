/**
 * Customer portal: play bumper → main recording → bumper (same intro/outro asset).
 * Bumper segments are muted; main recording plays with sound (user can mute in controls).
 */
(function () {
  function readBumperUrl(video) {
    const el = video.querySelector("source[src]");
    return el ? el.getAttribute("src") || "" : "";
  }

  function setMp4Source(video, url) {
    video.textContent = "";
    const src = document.createElement("source");
    src.src = url;
    src.type = "video/mp4";
    video.appendChild(src);
    video.load();
  }

  function applyMuteForPhase(video, phase, useBumper) {
    if (!useBumper) {
      video.muted = false;
      return;
    }
    video.muted = phase !== 1;
  }

  function playMaybe(video) {
    const p = video.play();
    if (p && typeof p.catch === "function") {
      p.catch(function () {});
    }
  }

  document.querySelectorAll("video.portal-bumper-video[data-main-src]").forEach(function (video) {
    var mainSrc = video.dataset.mainSrc;
    if (!mainSrc) {
      return;
    }
    var bumper = readBumperUrl(video);
    if (!bumper) {
      setMp4Source(video, mainSrc);
      video.muted = false;
      return;
    }

    var phase = 0;
    var useBumper = true;

    applyMuteForPhase(video, phase, useBumper);

    video.addEventListener("playing", function () {
      if (useBumper && phase !== 1) {
        video.muted = true;
      }
    });

    video.addEventListener("ended", function () {
      if (!useBumper) {
        video.pause();
        video.currentTime = 0;
        return;
      }
      if (phase === 0) {
        phase = 1;
        setMp4Source(video, mainSrc);
        applyMuteForPhase(video, phase, useBumper);
        playMaybe(video);
      } else if (phase === 1) {
        phase = 2;
        setMp4Source(video, bumper);
        applyMuteForPhase(video, phase, useBumper);
        playMaybe(video);
      } else {
        phase = 0;
        video.pause();
        setMp4Source(video, bumper);
        applyMuteForPhase(video, phase, useBumper);
        video.load();
      }
    });

    video.addEventListener("error", function onErr() {
      if (phase !== 0) {
        return;
      }
      video.removeEventListener("error", onErr);
      useBumper = false;
      phase = 1;
      setMp4Source(video, mainSrc);
      applyMuteForPhase(video, phase, useBumper);
      video.load();
      playMaybe(video);
    });
  });
})();
