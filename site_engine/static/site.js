/* Mobile menu */
(function(){
  document.querySelectorAll('.menu-toggle').forEach(function(btn){
    btn.addEventListener('click',function(){
      var wrap = btn.closest('.nav-wrap');
      var links = wrap && wrap.querySelector('.nav-links');
      var open = btn.getAttribute('aria-expanded') === 'true';
      btn.setAttribute('aria-expanded', String(!open));
      if(links){
        if(!open){
          links.style.cssText = 'display:flex;flex-direction:column;position:absolute;top:74px;left:16px;right:16px;padding:20px;border-radius:20px;background:var(--surface);border:1px solid var(--border);box-shadow:var(--shadow);z-index:100;gap:4px';
        } else {
          links.style.display = 'none';
        }
      }
    });
  });
})();

/* Scroll reveal */
(function(){
  var io = new IntersectionObserver(function(entries){
    entries.forEach(function(e){
      if(e.isIntersecting){
        e.target.classList.add('se-visible');
        io.unobserve(e.target);
      }
    });
  },{threshold:0.07,rootMargin:'0px 0px -40px 0px'});

  var style = document.createElement('style');
  style.textContent =
    '.se-reveal{opacity:0;transform:translateY(18px);transition:opacity .65s cubic-bezier(.22,.9,.36,1),transform .65s cubic-bezier(.22,.9,.36,1)}' +
    '.se-visible{opacity:1!important;transform:none!important}' +
    '.se-reveal:nth-child(2){transition-delay:.08s}' +
    '.se-reveal:nth-child(3){transition-delay:.16s}' +
    '.se-reveal:nth-child(4){transition-delay:.24s}' +
    '.se-reveal:nth-child(5){transition-delay:.32s}';
  document.head.appendChild(style);

  document.querySelectorAll('.site-section:not(.navbar)').forEach(function(sec){
    sec.classList.add('se-reveal');
    io.observe(sec);
  });
})();

/* Smooth anchor links */
document.querySelectorAll('a[href^="#"]').forEach(function(a){
  a.addEventListener('click',function(e){
    var id = a.getAttribute('href');
    var target = document.querySelector(id);
    if(target){
      e.preventDefault();
      target.scrollIntoView({behavior:'smooth',block:'start'});
    }
  });
});

/* FAQ toggle icon */
document.querySelectorAll('.faq-item').forEach(function(item){
  item.addEventListener('toggle',function(){
    var span = item.querySelector('summary span');
    if(span) span.textContent = item.open ? '−' : '+';
  });
});
