'use client';

import React, { useState, useEffect, useRef } from 'react';
import Link from 'next/link';
import { motion, AnimatePresence } from 'framer-motion';
import { Check, ArrowRight } from 'lucide-react';

// Custom useTypewriter hook
function useTypewriter(text: string, speed: number = 38, startDelay: number = 600) {
  const [displayed, setDisplayed] = useState('');
  const [done, setDone] = useState(false);

  useEffect(() => {
    let timeoutId: NodeJS.Timeout;
    let intervalId: NodeJS.Timeout;

    timeoutId = setTimeout(() => {
      let index = 0;
      intervalId = setInterval(() => {
        if (index < text.length) {
          setDisplayed((prev) => prev + text.charAt(index));
          index++;
        } else {
          setDone(true);
          clearInterval(intervalId);
        }
      }, speed);
    }, startDelay);

    return () => {
      clearTimeout(timeoutId);
      if (intervalId) clearInterval(intervalId);
    };
  }, [text, speed, startDelay]);

  return { displayed, done };
}

export default function LandingPage() {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [selectedServices, setSelectedServices] = useState<string[]>([]);
  const videoRef = useRef<HTMLVideoElement>(null);
  const prevXRef = useRef<number | null>(null);

  // Typewriter hook
  const { displayed, done } = useTypewriter("find every local lead\nunder the sun!", 38, 600);

  const services = ["Real Estate", "Salons", "Restaurants", "Gyms", "Clinics", "Boutiques"];

  const toggleService = (service: string) => {
    setSelectedServices((prev) =>
      prev.includes(service)
        ? prev.filter((s) => s !== service)
        : [...prev, service]
    );
  };

  // Background Video Native Scrubbing and Autoplay Logic
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    // Handle mobile autoplay (< 1024px)
    const handleResize = () => {
      if (window.innerWidth < 1024) {
        video.autoplay = true;
        video.play().catch(() => {});
      } else {
        video.pause();
      }
    };

    handleResize();
    window.addEventListener('resize', handleResize);

    // Seeked listener for smooth tracking
    const handleSeeked = () => {
      // Seek completed smoothly
    };
    video.addEventListener('seeked', handleSeeked);

    // Desktop mouse move scrubbing (>= 1024px)
    const handleMouseMove = (e: MouseEvent) => {
      if (window.innerWidth < 1024) return;
      if (!video.duration) return;

      const currentX = e.clientX;
      if (prevXRef.current === null) {
        prevXRef.current = currentX;
        return;
      }

      const deltaX = currentX - prevXRef.current;
      prevXRef.current = currentX;

      const duration = video.duration;
      // Calculate target scrub time based on speed ratio
      const targetTimeDelta = (deltaX / window.innerWidth) * 0.8 * duration;
      let targetTime = video.currentTime + targetTimeDelta;

      // Clamp target scrub time between 0 and video duration
      if (targetTime < 0) targetTime = 0;
      if (targetTime > duration) targetTime = duration;

      video.currentTime = targetTime;
    };

    const handleMouseLeave = () => {
      prevXRef.current = null;
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseleave', handleMouseLeave);

    return () => {
      window.removeEventListener('resize', handleResize);
      video.removeEventListener('seeked', handleSeeked);
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseleave', handleMouseLeave);
    };
  }, []);

  return (
    <div className="relative bg-white text-neutral-900 font-sans selection:bg-[#EAECE9] selection:text-[#1C2E1E] antialiased overflow-x-hidden flex flex-col lg:block lg:min-h-screen">
      
      {/* Background Video Component (with Native Scrubbing) */}
      <div className="order-last lg:order-none relative lg:absolute lg:inset-0 lg:z-0 overflow-hidden pointer-events-none w-full aspect-square md:aspect-video lg:aspect-auto lg:h-full bg-neutral-50 lg:bg-transparent">
        <video
          ref={videoRef}
          muted
          playsInline
          preload="auto"
          src="https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260601_110537_3a579fa0-7bbc-4d94-9d25-0e816c7840f5.mp4"
          className="w-full h-full object-cover object-right lg:object-right-bottom"
        />
      </div>

      {/* Interactive Navbar */}
      <header className="fixed top-0 inset-x-0 z-10 px-5 sm:px-8 py-4 sm:py-5 flex flex-row justify-between items-center bg-transparent">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-2 select-none group">
          <span className="text-[21px] sm:text-[26px] tracking-tight text-black font-semibold">
            Lead Finder®
          </span>
          <span className="text-[25px] sm:text-[30px] text-black tracking-[-0.02em] font-medium leading-none mb-1">
            &#10033;
          </span>
        </Link>

        {/* Desktop Nav Links */}
        <nav className="hidden md:flex flex-row items-center text-[23px] text-black">
          <Link href="/dashboard" className="hover:opacity-60 transition-opacity">Scraper</Link>
          <span className="opacity-40">,&nbsp;</span>
          <Link href="/dashboard" className="hover:opacity-60 transition-opacity">Outreach</Link>
          <span className="opacity-40">,&nbsp;</span>
          <Link href="/dashboard" className="hover:opacity-60 transition-opacity">History</Link>
          <span className="opacity-40">,&nbsp;</span>
          <Link href="/dashboard" className="hover:opacity-60 transition-opacity">Docs</Link>
        </nav>

        {/* Desktop CTA */}
        <div className="hidden md:block">
          <Link 
            href="/dashboard" 
            className="text-[23px] text-black underline underline-offset-2 hover:opacity-60 transition-opacity"
          >
            Launch Dashboard
          </Link>
        </div>

        {/* Mobile Menu Button */}
        <button 
          onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
          className="flex flex-col gap-1.5 justify-center items-center md:hidden z-20 w-8 h-8 relative focus:outline-none"
          aria-label="Toggle Menu"
        >
          <span className={`w-6 h-[2px] bg-black transition-all duration-300 ${isMobileMenuOpen ? 'rotate-45 translate-y-[8px]' : ''}`} />
          <span className={`w-6 h-[2px] bg-black transition-all duration-300 ${isMobileMenuOpen ? 'opacity-0' : ''}`} />
          <span className={`w-6 h-[2px] bg-black transition-all duration-300 ${isMobileMenuOpen ? '-rotate-45 -translate-y-[8px]' : ''}`} />
        </button>
      </header>

      {/* Mobile Navigation Overlay */}
      <div 
        className={`fixed inset-0 z-[9] bg-white/95 backdrop-blur-sm transition-all duration-300 md:hidden flex flex-col justify-center items-center gap-8 ${
          isMobileMenuOpen ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'
        }`}
      >
        <Link 
          href="/dashboard" 
          onClick={() => setIsMobileMenuOpen(false)}
          className="text-2xl text-black hover:opacity-60 transition-opacity"
        >
          Scraper
        </Link>
        <Link 
          href="/dashboard" 
          onClick={() => setIsMobileMenuOpen(false)}
          className="text-2xl text-black hover:opacity-60 transition-opacity"
        >
          Outreach
        </Link>
        <Link 
          href="/dashboard" 
          onClick={() => setIsMobileMenuOpen(false)}
          className="text-2xl text-black hover:opacity-60 transition-opacity"
        >
          History
        </Link>
        <Link 
          href="/dashboard" 
          onClick={() => setIsMobileMenuOpen(false)}
          className="text-2xl text-black hover:opacity-60 transition-opacity"
        >
          Docs
        </Link>
        <Link 
          href="/dashboard" 
          onClick={() => setIsMobileMenuOpen(false)}
          className="rounded-full bg-[#1C2E1E] text-white px-8 py-3 text-lg font-medium shadow-md shadow-[#1C2E1E]/20 hover:scale-[1.03] transition-all mt-4"
        >
          Launch Dashboard
        </Link>
      </div>

      {/* Content Layout Container */}
      <div className="relative z-10 flex flex-col order-first lg:order-none w-full bg-white lg:bg-transparent pb-8 lg:pb-0 lg:min-h-screen">
        <main id="spade-hero" className="w-full max-w-7xl mx-auto px-6 py-12 sm:py-20 lg:py-24 flex-1 flex flex-col justify-center min-h-[85vh] lg:min-h-screen pt-24 sm:pt-32">
          
          {/* Headline Section */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
            className="w-full"
          >
            <h1 className="text-5xl md:text-6xl lg:text-[76px] font-normal tracking-tight text-black leading-[1.08] mb-8 select-none w-full whitespace-pre-wrap">
              {displayed}
              {!done && (
                <span className="inline-block w-[2px] h-[1.1em] bg-black align-middle ml-[2px] animate-blink" />
              )}
            </h1>
          </motion.div>

          {/* Description text */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.1 }}
          >
            <p className="text-lg md:text-xl text-[#5A635A] leading-relaxed font-normal mb-12 max-w-2xl">
              Locate target businesses, scrape verified email addresses, <br className="hidden sm:inline" />
              and track your cold outreach campaigns with zero subscription or API key fees.
            </p>
          </motion.div>

          {/* Interactive Service Pills */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.2 }}
            className="w-full max-w-3xl"
          >
            <h2 className="text-2xl font-medium tracking-tight mb-2 text-black">
              What sort of leads?
            </h2>
            <p className="opacity-85 text-[#738273] mb-8 text-sm sm:text-base">
              Select all that apply
            </p>

            <div className="flex flex-wrap gap-3 mb-8">
              {services.map((service) => {
                const isActive = selectedServices.includes(service);
                return (
                  <motion.button
                    key={service}
                    onClick={() => toggleService(service)}
                    whileHover={{ scale: 1.02 }}
                    whileTap={{ scale: 0.98 }}
                    className={`flex items-center gap-2 px-6 py-3 rounded-full text-base font-medium cursor-pointer transition-all duration-250 ${
                      isActive
                        ? 'bg-[#1C2E1E] text-white shadow-md shadow-emerald-950/5'
                        : 'bg-white text-[#1C2E1E] border border-[#F1F3F1] hover:bg-[#F1F3F1]/55'
                    }`}
                  >
                    {isActive && (
                      <motion.span
                        initial={{ scale: 0, opacity: 0 }}
                        animate={{ scale: 1, opacity: 1 }}
                        transition={{ type: "spring", stiffness: 300, damping: 20 }}
                      >
                        <Check className="w-4 h-4 text-white" />
                      </motion.span>
                    )}
                    {service}
                  </motion.button>
                );
              })}
            </div>

            {/* Contingent Feedback Banner */}
            <div className="min-h-[50px]">
              <AnimatePresence mode="wait">
                {selectedServices.length === 0 ? (
                  <motion.p
                    key="empty"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 0.5 }}
                    exit={{ opacity: 0 }}
                    className="italic text-xs text-[#5A635A]"
                  >
                    Please click to select lead categories above.
                  </motion.p>
                ) : (
                  <motion.div
                    key="selected"
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.2 }}
                    className="overflow-hidden"
                  >
                    <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center p-4 bg-[#FAFBF9] border border-[#F1F3F1] rounded-2xl gap-3">
                      <div className="text-xs uppercase tracking-wider text-[#4D6D47] font-semibold">
                        Ready to scrape: <span className="text-black font-normal normal-case ml-1">{selectedServices.join(', ')}</span>
                      </div>
                      <Link
                        href="/dashboard"
                        className="inline-flex items-center gap-2 text-xs uppercase tracking-wider text-[#4D6D47] font-bold hover:opacity-80 transition-opacity"
                      >
                        Let's Go
                        <ArrowRight className="w-3.5 h-3.5" />
                      </Link>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

          </motion.div>
        </main>
      </div>

    </div>
  );
}
