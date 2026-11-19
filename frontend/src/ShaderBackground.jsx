import { useEffect, useRef } from "react";

/**
 * WebGL Flowing Dual-Palette Shader Background
 * Dark mode: Warm espresso brown, toasted walnut, and amber/white highlights
 * Light mode: Beige paper with a faint charcoal grain
 */
export default function ShaderBackground() {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const gl = canvas.getContext("webgl") || canvas.getContext("experimental-webgl");
    if (!gl) return;

    // Vertex shader
    const vsSource = `
      attribute vec2 a_position;
      void main() {
        gl_Position = vec4(a_position, 0.0, 1.0);
      }
    `;

    // Fragment shader with dual palette support
    const fsSource = `
      precision mediump float;
      uniform vec2 u_resolution;
      uniform float u_time;
      uniform vec2 u_mouse;
      uniform float u_is_dark;

      void main() {
        vec2 st = gl_FragCoord.xy / u_resolution.xy;
        st.x *= u_resolution.x / u_resolution.y;

        vec2 mouse = u_mouse / u_resolution.xy;
        mouse.x *= u_resolution.x / u_resolution.y;

        float t = u_time * 0.35;
        
        // Multi-frequency wave pattern
        float q1 = sin(st.x * 2.4 + t + sin(st.y * 2.8 + t * 0.4));
        float q2 = cos(st.y * 3.0 - t * 0.7 + cos(st.x * 2.5 - t * 0.3));
        float wave = (q1 + q2) * 0.5;

        float d = distance(st, mouse);
        float mouseGlow = smoothstep(0.65, 0.0, d) * 0.3;

        // Palette definitions
        // Dark: Rich espresso brown (0.07, 0.045, 0.03) -> Warm chocolate (0.22, 0.14, 0.09) -> Copper/Caramel (0.75, 0.50, 0.28)
        vec3 darkBase = vec3(0.07, 0.045, 0.03);
        vec3 darkMid = vec3(0.22, 0.14, 0.09);
        vec3 darkAccent = vec3(0.75, 0.50, 0.28);

        // Light: warm paper, deeper beige, near-black ink kept very faint
        vec3 lightBase = vec3(0.957, 0.937, 0.902);
        vec3 lightMid = vec3(0.906, 0.875, 0.824);
        vec3 lightAccent = vec3(0.067, 0.067, 0.067);

        vec3 cBase = mix(lightBase, darkBase, u_is_dark);
        vec3 cMid = mix(lightMid, darkMid, u_is_dark);
        vec3 cAccent = mix(lightAccent, darkAccent, u_is_dark);

        float accentAmt = clamp(pow(max(0.0, wave * 0.75 + mouseGlow), 3.2), 0.0, 1.0);
        accentAmt *= mix(0.16, 1.0, u_is_dark);

        vec3 color = mix(cBase, cMid, clamp(wave + 0.4 + mouseGlow, 0.0, 1.0) * mix(0.55, 1.0, u_is_dark));
        color = mix(color, cAccent, accentAmt);

        vec2 uv = gl_FragCoord.xy / u_resolution.xy;
        float vignette = uv.x * uv.y * (1.0 - uv.x) * (1.0 - uv.y);
        vignette = clamp(pow(16.0 * vignette, 0.3), 0.0, 1.0);

        float alpha = mix(0.22, 0.75, u_is_dark);
        gl_FragColor = vec4(color * vignette, alpha);
      }
    `;

    function createShader(type, source) {
      const shader = gl.createShader(type);
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        gl.deleteShader(shader);
        return null;
      }
      return shader;
    }

    const vs = createShader(gl.VERTEX_SHADER, vsSource);
    const fs = createShader(gl.FRAGMENT_SHADER, fsSource);
    if (!vs || !fs) return;

    const program = gl.createProgram();
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return;

    gl.useProgram(program);

    const positionBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([
        -1, -1,
         1, -1,
        -1,  1,
        -1,  1,
         1, -1,
         1,  1,
      ]),
      gl.STATIC_DRAW
    );

    const positionLoc = gl.getAttribLocation(program, "a_position");
    gl.enableVertexAttribArray(positionLoc);
    gl.vertexAttribPointer(positionLoc, 2, gl.FLOAT, false, 0, 0);

    const resLoc = gl.getUniformLocation(program, "u_resolution");
    const timeLoc = gl.getUniformLocation(program, "u_time");
    const mouseLoc = gl.getUniformLocation(program, "u_mouse");
    const isDarkLoc = gl.getUniformLocation(program, "u_is_dark");

    let mouse = [canvas.width * 0.5, canvas.height * 0.5];
    let targetMouse = [...mouse];

    function onMouseMove(e) {
      const rect = canvas.getBoundingClientRect();
      targetMouse[0] = e.clientX - rect.left;
      targetMouse[1] = canvas.height - (e.clientY - rect.top);
    }

    window.addEventListener("mousemove", onMouseMove, { passive: true });

    function resize() {
      const w = canvas.parentElement?.clientWidth || window.innerWidth;
      const h = canvas.parentElement?.clientHeight || 650;
      canvas.width = Math.min(w, 1920);
      canvas.height = h;
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.uniform2f(resLoc, canvas.width, canvas.height);
    }

    resize();
    window.addEventListener("resize", resize);

    let animationId;
    let startTime = performance.now();

    function render(currentTime) {
      const elapsed = (currentTime - startTime) * 0.001;
      const isDark = document.documentElement.getAttribute("data-theme") !== "light" ? 1.0 : 0.0;

      // LERP mouse coordinates smoothly
      mouse[0] += (targetMouse[0] - mouse[0]) * 0.05;
      mouse[1] += (targetMouse[1] - mouse[1]) * 0.05;

      gl.uniform1f(timeLoc, elapsed);
      gl.uniform2f(mouseLoc, mouse[0], mouse[1]);
      gl.uniform1f(isDarkLoc, isDark);

      gl.drawArrays(gl.TRIANGLES, 0, 6);
      animationId = requestAnimationFrame(render);
    }

    animationId = requestAnimationFrame(render);

    return () => {
      cancelAnimationFrame(animationId);
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("resize", resize);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="raca-shader-canvas"
      aria-hidden="true"
    />
  );
}

