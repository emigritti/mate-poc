// Shared Framer Motion variants — keep durations short for enterprise SaaS feel

export const fadeIn = {
  hidden: { opacity: 0 },
  show:   { opacity: 1, transition: { duration: 0.18 } },
  exit:   { opacity: 0, transition: { duration: 0.12 } },
};

export const fadeUp = {
  hidden: { opacity: 0, y: 10 },
  show:   { opacity: 1, y: 0,  transition: { duration: 0.22, ease: 'easeOut' } },
  exit:   { opacity: 0, y: -6, transition: { duration: 0.14, ease: 'easeIn'  } },
};

export const staggerContainer = {
  hidden: {},
  show: {
    transition: {
      staggerChildren: 0.055,
      delayChildren:   0.04,
    },
  },
};

// For individual items inside a staggered container
export const staggerItem = {
  hidden: { opacity: 0, y: 10 },
  show:   { opacity: 1, y: 0,  transition: { duration: 0.22, ease: 'easeOut' } },
};

// Subtle scale-in for cards that don't need vertical travel
export const scaleIn = {
  hidden: { opacity: 0, scale: 0.97 },
  show:   { opacity: 1, scale: 1,    transition: { duration: 0.2,  ease: 'easeOut' } },
};
