import { askLLM } from "@/utils/askLlm";
import { config } from "@/utils/config";
import { handleSocialMediaActions } from "@/features/externalAPI/utils/socialMediaHandler";
import { sendToClients } from "@/features/externalAPI/utils/apiHelper";

/**
 * Speak text directly via TTS, bypassing the LLM entirely.
 * The browser SSE handler echoes the text through the TTS pipeline.
 * Used by Claude Code REPL to give the avatar a voice during live sessions.
 */
export const speakDirect = (text: string): void => {
  sendToClients({ type: "normal", data: text });
};


export const processNormalChat = async (message: string): Promise<string> => {
  return await askLLM(config("system_prompt"), message, null);
};

export const triggerAmicaActions = async (payload: any) => {
  const { text, socialMedia, playback, reprocess, animation } = payload;

  if (text) {
    const message = reprocess
      ? await askLLM(config("system_prompt"), text, null)
      : text;
    await handleSocialMediaActions(message, socialMedia);
  }

  if (playback) {
    sendToClients({ type: "playback", data: 10000 });
  }

  if (animation) {
    sendToClients({ type: "animation", data: animation });
  }
};

export const updateSystemPrompt = async (payload: any): Promise<any> => {
    const { prompt } = payload;
    let response = sendToClients({ type: "systemPrompt", data: prompt });
    return response;
  };
  
