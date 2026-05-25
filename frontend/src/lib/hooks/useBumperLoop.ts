"use client";

import { useRef, useCallback } from "react";

interface BumperLoopOptions {
  bumperSrc: string | null;
  mainSrc: string;
}

export function useBumperLoop({ bumperSrc, mainSrc }: BumperLoopOptions) {
  const phaseRef = useRef<0 | 1 | 2>(0);
  const useBumperRef = useRef(!!bumperSrc);
  const videoRef = useRef<HTMLVideoElement>(null);

  const setSource = useCallback((video: HTMLVideoElement, src: string) => {
    video.src = src;
    video.load();
  }, []);

  const applyMute = useCallback((video: HTMLVideoElement) => {
    video.muted = useBumperRef.current && phaseRef.current !== 1;
  }, []);

  const playMaybe = useCallback((video: HTMLVideoElement) => {
    const p = video.play();
    if (p) p.catch(() => {});
  }, []);

  const onEnded = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    if (!useBumperRef.current) {
      video.pause();
      video.currentTime = 0;
      return;
    }
    if (phaseRef.current === 0) {
      phaseRef.current = 1;
      setSource(video, mainSrc);
      applyMute(video);
      playMaybe(video);
    } else if (phaseRef.current === 1) {
      phaseRef.current = 2;
      setSource(video, bumperSrc!);
      applyMute(video);
      playMaybe(video);
    } else {
      phaseRef.current = 0;
      video.pause();
      setSource(video, bumperSrc!);
      applyMute(video);
    }
  }, [bumperSrc, mainSrc, setSource, applyMute, playMaybe]);

  const onError = useCallback(() => {
    const video = videoRef.current;
    if (!video || phaseRef.current !== 0) return;
    useBumperRef.current = false;
    phaseRef.current = 1;
    setSource(video, mainSrc);
    applyMute(video);
    video.load();
    playMaybe(video);
  }, [mainSrc, setSource, applyMute, playMaybe]);

  const onPlaying = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    applyMute(video);
  }, [applyMute]);

  const getInitialSrc = () => bumperSrc || mainSrc;
  const getInitialMuted = () => !!bumperSrc;

  return { videoRef, onEnded, onError, onPlaying, getInitialSrc, getInitialMuted };
}
