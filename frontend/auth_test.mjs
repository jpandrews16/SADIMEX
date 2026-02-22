import { createClient } from '@supabase/supabase-js';
import fs from 'fs';

const envFile = fs.readFileSync('.env.local', 'utf-8');
const env = {};
envFile.split('\n').forEach(line => {
  const [k, ...v] = line.split('=');
  if (k && v.length) env[k.trim()] = v.join('=').trim();
});

const supabase = createClient(env.VITE_SUPABASE_URL, env.VITE_SUPABASE_ANON_KEY);

async function run() {
    let email = 'jpandrews';
    try {
        if (!email.includes('@')) {
            const { data: profiles, error: profileErr } = await supabase
                .from('sadimex_profiles')
                .select('email')
                .eq('username', email)
                .limit(1);

            if (profileErr) throw profileErr;
            if (!profiles || profiles.length === 0) {
                console.log("No user found");
                return;
            }
            email = profiles[0].email;
            console.log("Found email:", email);
        }

        const { data, error } = await supabase.auth.signInWithPassword({
            email,
            password: 'Cuidadingo1'
        });

        if (error) {
            console.log("Sigin in error:", error);
            return;
        }

        const { data: profile, error: profErr } = await supabase
            .from('sadimex_profiles')
            .select('*')
            .eq('id', data.user.id)
            .single();

        if (profErr) {
            console.log("Profile err:", profErr);
            return;
        }
        
        console.log("Success!", profile);

    } catch (err) {
        console.log("CAUGHT ERR:", err);
    }
}
run();
